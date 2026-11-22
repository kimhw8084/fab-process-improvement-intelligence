import unittest
from fabintel.project import slope, feasible_observed, analyze
class SpecializedTests(unittest.TestCase):
 def test_known_slope(self): self.assertAlmostEqual(slope([1,2,3,4],[2,4,6,8]),2)
 def test_only_observed_candidates(self):
  obs=[{'factor':x,'response':2*x} for x in (1,2,3,4)]
  self.assertEqual(feasible_observed(obs,1,4,5),[3,4])
 def test_missing_constraints(self):
  self.assertEqual(analyze({'constraints_approved':False})['status'],'REFUSED')
