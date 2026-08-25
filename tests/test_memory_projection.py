from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from history import EpistemicObject, StateDelta, StateProjector, Supersession  # noqa: E402
from memory_projection import MemoryProjection  # noqa: E402


class MemoryProjectionTests(unittest.TestCase):
    def make_state(self):
        p=StateProjector()
        a=EpistemicObject.create(object_id='C-1',object_type='CLAIM',content={'topic':'bridge','status':'inspection pending'})
        b=EpistemicObject.create(object_id='E-1',object_type='EVIDENCE',content={'topic':'bridge','finding':'corrosion'})
        p.apply(StateDelta((a,b),()))
        return p

    def test_projection_is_rebuilt_from_active_state(self):
        state=self.make_state(); memory=MemoryProjection(); memory.rebuild(state.snapshot())
        self.assertEqual(memory.state_ref,state.state_ref)
        self.assertEqual({x.object_id for x in memory.records},{'C-1','E-1'})
        hits=memory.search('bridge corrosion')
        self.assertEqual(hits[0].object_id,'E-1')
        self.assertTrue(all(x.state_ref==state.state_ref for x in hits))

    def test_superseded_object_disappears_after_rebuild(self):
        state=self.make_state(); replacement=EpistemicObject.create(object_id='C-2',object_type='CLAIM',content={'topic':'bridge','status':'inspection complete'})
        state.apply(StateDelta((replacement,),(Supersession('C-1','C-2'),)))
        memory=MemoryProjection(); memory.rebuild(state.snapshot())
        self.assertNotIn('C-1',{x.object_id for x in memory.records})
        self.assertIn('C-2',{x.object_id for x in memory.records})

    def test_rebuild_is_deterministic_and_disposable(self):
        state=self.make_state(); a=MemoryProjection(); b=MemoryProjection()
        a.rebuild(state.snapshot()); b.rebuild(state.snapshot())
        self.assertEqual(a.records,b.records)
        self.assertEqual(a.search('bridge'),b.search('bridge'))

    def test_projection_has_no_direct_remember_or_commit_api(self):
        memory=MemoryProjection()
        self.assertFalse(hasattr(memory,'remember'))
        self.assertFalse(hasattr(memory,'remember_explicit'))
        self.assertFalse(hasattr(memory,'commit'))
        self.assertFalse(hasattr(memory,'add_object'))

    def test_type_filter_is_projection_only(self):
        state=self.make_state(); memory=MemoryProjection(); memory.rebuild(state.snapshot())
        hits=memory.search('bridge',object_types=('EVIDENCE',))
        self.assertEqual([x.object_id for x in hits],['E-1'])

if __name__=='__main__': unittest.main()
