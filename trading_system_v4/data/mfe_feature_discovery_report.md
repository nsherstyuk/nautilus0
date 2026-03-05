# MFE Feature Discovery Report

Rows: 10,139
Features evaluated: 40

## Top 20 Features by edge_score

- atr_sma50: edge=0.2373, fold_ic=0.1113±0.0413, mfe_spread=0.7096, hit_spread=0.1144
- atr_norm: edge=0.2288, fold_ic=0.1176±0.0374, mfe_spread=0.6359, hit_spread=0.1124
- avg_spread: edge=0.1214, fold_ic=0.0382±0.0242, mfe_spread=0.4930, hit_spread=0.0533
- buy_volume: edge=0.1032, fold_ic=-0.0397±0.0196, mfe_spread=-0.3649, hit_spread=-0.0385
- total_volume: edge=0.1025, fold_ic=-0.0474±0.0179, mfe_spread=-0.3185, hit_spread=-0.0355
- spread_sma5: edge=0.1008, fold_ic=0.0361±0.0228, mfe_spread=0.4046, hit_spread=0.0404
- edge_regime_trend_align: edge=0.0998, fold_ic=0.0631±0.0245, mfe_spread=0.2551, hit_spread=0.0789
- sell_volume: edge=0.0863, fold_ic=-0.0429±0.0278, mfe_spread=-0.3195, hit_spread=-0.0513
- tick_velocity_sma5: edge=0.0831, fold_ic=0.0238±0.0521, mfe_spread=-0.4970, hit_spread=-0.0256
- max_spread: edge=0.0727, fold_ic=0.0432±0.0303, mfe_spread=0.2741, hit_spread=0.0402
- edge_imbalance_regime_delta: edge=0.0637, fold_ic=-0.0008±0.0145, mfe_spread=0.4018, hit_spread=0.0325
- dist_to_high_50: edge=0.0619, fold_ic=0.0098±0.0208, mfe_spread=0.3645, hit_spread=0.0473
- volatility_regime: edge=0.0614, fold_ic=0.0238±0.0086, mfe_spread=0.1883, hit_spread=0.0325
- tick_velocity: edge=0.0591, fold_ic=0.0161±0.0523, mfe_spread=-0.3584, hit_spread=-0.0128
- dist_to_high_10: edge=0.0422, fold_ic=-0.0035±0.0307, mfe_spread=-0.2684, hit_spread=-0.0108
- edge_trend_accel: edge=0.0402, fold_ic=-0.0131±0.0226, mfe_spread=-0.2342, hit_spread=-0.0178
- ret_10: edge=0.0370, fold_ic=0.0022±0.0369, mfe_spread=-0.2374, hit_spread=-0.0089
- ret_50: edge=0.0349, fold_ic=0.0089±0.0247, mfe_spread=0.2007, hit_spread=0.0256
- tick_velocity_ratio: edge=0.0255, fold_ic=-0.0160±0.0225, mfe_spread=0.1337, hit_spread=-0.0148
- price_vol_divergence: edge=0.0232, fold_ic=-0.0091±0.0310, mfe_spread=-0.1297, hit_spread=-0.0143

## Candidate engineered features included

- edge_vel_over_spread
- edge_imbalance_x_velocity
- edge_imbalance_regime_delta
- edge_trend_accel
- edge_breakout_distance
- edge_regime_trend_align