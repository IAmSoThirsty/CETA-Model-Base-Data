import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from authority import AuthorityBindingError, AuthorityLedger, Permit, PermitExpiredError, PermitReuseError, PermitStatus, canonical_hash

class AuthorityLedgerTests(unittest.TestCase):
    def make(self, **kw):
        consequence=kw.pop('consequence',{'effect':'write','resource':'/bounded/file'})
        p=Permit(
            permit_id=kw.pop('permit_id','P1'), nonce=kw.pop('nonce','N1'), policy_epoch='E1',
            subject_scope=kw.pop('subject_scope','/bounded'), operation='Execute', consequence_hash=canonical_hash(consequence),
            consumer_id=kw.pop('consumer_id','exec-1'), consumer_key_id=kw.pop('consumer_key_id','key-1'),
            expires_at_epoch_ms=kw.pop('expires_at_epoch_ms',1000), source_refs=('T1',), use_limit=kw.pop('use_limit',1), **kw)
        return p, consequence

    def test_empty_scope_is_rejected_at_issue_boundary(self):
        p,c=self.make(subject_scope='')
        ledger=AuthorityLedger()
        with self.assertRaises(AuthorityBindingError): ledger.issue(p,consequence=c,now_ms=1)

    def test_exact_consumer_key_is_required(self):
        p,c=self.make(); l=AuthorityLedger(); l.issue(p,consequence=c,now_ms=1)
        with self.assertRaises(AuthorityBindingError): l.prepare('P1',consumer_id='exec-1',consumer_key_id='wrong',consequence=c,now_ms=2)

    def test_exact_consequence_is_required(self):
        p,c=self.make(); l=AuthorityLedger(); l.issue(p,consequence=c,now_ms=1)
        with self.assertRaises(AuthorityBindingError): l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence={'effect':'delete','resource':'/bounded/file'},now_ms=2)

    def test_nonce_is_monotonic_after_consumption(self):
        p,c=self.make(); l=AuthorityLedger(); l.issue(p,consequence=c,now_ms=1)
        intent=l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence=c,now_ms=2)
        l.consume('P1',consumer_id='exec-1',consumer_key_id='key-1',intent_hash=intent,now_ms=3)
        self.assertTrue(l.consumed('N1'))
        p2,c2=self.make(permit_id='P2',nonce='N1')
        with self.assertRaises(PermitReuseError): l.issue(p2,consequence=c2,now_ms=4)

    def test_consumed_permit_cannot_be_revoked(self):
        p,c=self.make(); l=AuthorityLedger(); l.issue(p,consequence=c,now_ms=1)
        i=l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence=c,now_ms=2)
        l.consume('P1',consumer_id='exec-1',consumer_key_id='key-1',intent_hash=i,now_ms=3)
        with self.assertRaises(AuthorityBindingError): l.revoke('P1')

    def test_completed_receipt_must_match_consequence(self):
        p,c=self.make(); l=AuthorityLedger(); l.issue(p,consequence=c,now_ms=1)
        i=l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence=c,now_ms=2)
        l.consume('P1',consumer_id='exec-1',consumer_key_id='key-1',intent_hash=i,now_ms=3)
        with self.assertRaises(AuthorityBindingError): l.finish('P1',status=PermitStatus.COMPLETED,expected_consequence_hash=p.consequence_hash,actual_consequence_hash='wrong')

    def test_indeterminate_requires_reconciliation(self):
        p,c=self.make(); l=AuthorityLedger(); l.issue(p,consequence=c,now_ms=1)
        i=l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence=c,now_ms=2)
        l.consume('P1',consumer_id='exec-1',consumer_key_id='key-1',intent_hash=i,now_ms=3)
        l.finish('P1',status=PermitStatus.INDETERMINATE,expected_consequence_hash=p.consequence_hash,actual_consequence_hash=None)
        l.reconcile('P1',resolved_status=PermitStatus.PARTIALLY_APPLIED)
        self.assertEqual(l.status('P1'),PermitStatus.PARTIALLY_APPLIED)

    def test_expired_prepare_revokes_durably_in_state_machine(self):
        p,c=self.make(expires_at_epoch_ms=10); l=AuthorityLedger(); l.issue(p,consequence=c,now_ms=1)
        with self.assertRaises(PermitExpiredError): l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence=c,now_ms=10)
        self.assertEqual(l.status('P1'),PermitStatus.REVOKED)

if __name__=='__main__': unittest.main()

class AuthorityDurabilityTests(unittest.TestCase):
    def make_permit(self, permit_id='P1', nonce='N1', expiry=1000):
        consequence={'effect':'write','resource':'/bounded/file'}
        return Permit(permit_id=permit_id,nonce=nonce,policy_epoch='E1',subject_scope='/bounded',operation='Execute',
                      consequence_hash=canonical_hash(consequence),consumer_id='exec-1',consumer_key_id='key-1',
                      expires_at_epoch_ms=expiry,source_refs=('T1',),use_limit=1), consequence

    def test_restart_preserves_consumed_nonce_and_terminal_status(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'authority.jsonl'
            p,c=self.make_permit(); l=AuthorityLedger(path); l.issue(p,consequence=c,now_ms=1)
            i=l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence=c,now_ms=2)
            l.consume('P1',consumer_id='exec-1',consumer_key_id='key-1',intent_hash=i,now_ms=3)
            l.finish('P1',status=PermitStatus.COMPLETED,expected_consequence_hash=p.consequence_hash,actual_consequence_hash=p.consequence_hash)
            l.verify()
            reopened=AuthorityLedger(path); reopened.verify()
            self.assertEqual(reopened.status('P1'),PermitStatus.COMPLETED)
            self.assertTrue(reopened.consumed('N1'))
            p2,c2=self.make_permit(permit_id='P2',nonce='N1')
            with self.assertRaises(PermitReuseError): reopened.issue(p2,consequence=c2,now_ms=4)

    def test_expiry_revocation_survives_restart(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'authority.jsonl'
            p,c=self.make_permit(expiry=10); l=AuthorityLedger(path); l.issue(p,consequence=c,now_ms=1)
            with self.assertRaises(PermitExpiredError): l.prepare('P1',consumer_id='exec-1',consumer_key_id='key-1',consequence=c,now_ms=10)
            reopened=AuthorityLedger(path)
            self.assertEqual(reopened.status('P1'),PermitStatus.REVOKED)

    def test_authority_event_tamper_is_rejected_on_restart(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'authority.jsonl'
            p,c=self.make_permit(); l=AuthorityLedger(path); l.issue(p,consequence=c,now_ms=1)
            raw=json.loads(path.read_text().strip()); raw['payload']['permit']['subject_scope']='*'
            path.write_text(json.dumps(raw)+'\n')
            with self.assertRaises(AuthorityBindingError): AuthorityLedger(path)
