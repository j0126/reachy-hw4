import unittest

import numpy as np

from reachy_motion.analysis.metrics import estimate_lag, peak_error, rmse


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.t = np.linspace(0.0, 2.0, 4001)
        self.y = np.sin(2 * np.pi * 1.3 * self.t) + 0.3 * self.t

    def test_identical_signals(self):
        self.assertAlmostEqual(rmse(self.t, self.y, self.t, self.y), 0.0)
        self.assertAlmostEqual(peak_error(self.t, self.y, self.t, self.y), 0.0)
        self.assertAlmostEqual(estimate_lag(self.t, self.y, self.t, self.y), 0.0)

    def test_constant_offset(self):
        self.assertAlmostEqual(rmse(self.t, self.y, self.t, self.y + 0.5), 0.5)
        self.assertAlmostEqual(peak_error(self.t, self.y, self.t, self.y - 0.25), 0.25)

    def test_recovers_a_known_delay_on_a_different_grid(self):
        delay = 0.030
        t_sig = np.arange(0.0, 2.0, 0.004)  # 250 Hz, not the reference grid
        y_sig = np.interp(t_sig - delay, self.t, self.y)
        lag = estimate_lag(self.t, self.y, t_sig, y_sig, max_lag=0.1, step=0.0005)
        self.assertAlmostEqual(lag, delay, delta=0.0005)
        lead = estimate_lag(self.t, self.y, t_sig, np.interp(t_sig + delay, self.t, self.y))
        self.assertAlmostEqual(lead, -delay, delta=0.0005)

    def test_no_overlap_raises(self):
        with self.assertRaises(ValueError):
            rmse(self.t, self.y, self.t + 10.0, self.y)


if __name__ == "__main__":
    unittest.main()
