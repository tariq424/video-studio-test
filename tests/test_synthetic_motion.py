import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from studio import graphics, physics
class MotionTests(unittest.TestCase):
    def test_priority(self):
        for vo in ['Radar sweeps over the coast.', 'Ships moving through Hormuz.', 'A train travels 300 km from A to B.']:
            self.assertEqual(graphics.classify({}, {'vo':vo}, lambda _:None)['template'],'motion')
        # owner, 2026-11-07: no number in the narration -> no modelled chart (it would be invented)
        self.assertNotEqual(graphics.classify({}, {'vo':'A train travels from A to B.'}, lambda _:None).get('template'),'motion')
        # no event to model (nothing rises, stops, falls or travels anywhere): no physics graph, graphics decide
        self.assertIsNone(physics.synthetic_motion({'vo':'Water flows through a river.'}))
    def test_non_motion(self):
        self.assertIsNone(physics.synthetic_motion({'vo':'The market moves higher.'}))
        self.assertIsNone(physics.synthetic_motion({'vo':'The ship has a steel hull.'}))
    def test_fallback(self):
        # no waypoints and no numbers: every value would be a typical fill-in -> nothing (owner, 2026-11-07: never invent numbers)
        self.assertIsNone(physics.run('ship_route',{}))
        self.assertIsNone(physics.run('weather_event',{}))   # no track and no strengthening: nothing honest to draw
    def test_explainer_router(self):
        import tempfile
        from unittest.mock import patch
        from studio import render
        for vo in ['Rain radar sweeps across the coast.', 'Ships move through the Strait of Hormuz.']:
            with tempfile.TemporaryDirectory() as folder, patch('studio.physics._fill', return_value={}):
                visual={'id':'v1'}
                rung=render.v2_after_wangp({},Path(folder),visual,vo,lambda _:None)
                self.assertEqual(rung,'simulation')
                self.assertNotEqual(visual['g']['kind'],'headline')
                self.assertTrue(visual['g']['synthetic'])
    def test_supplied_data_preserved(self):
        result=physics.run('ship_route',{'waypoints':[{'lat':26,'lon':56},{'lat':25.5,'lon':57}]})
        self.assertEqual(result['kind'],'simmap')
        self.assertNotEqual(result['source'],'synthetic')
        self.assertEqual(physics.route({'vo':'Radar sweeps across the coast.'}),'radar_sweep')
    def test_hormuz(self):
        result=physics.synthetic_motion({'vo':'Ships transit Hormuz.'})
        self.assertEqual(result['kind'],'simmap')
        self.assertGreater(len(result['track']),20)
        self.assertEqual(result['source'],'synthetic')
if __name__=='__main__': unittest.main()
