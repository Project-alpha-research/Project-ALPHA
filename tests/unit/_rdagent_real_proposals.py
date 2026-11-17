"""Real composite proposals from the second and third wide-universe RD-Agent runs.

Copied verbatim (keys and values) from the runs' loop logs; regression data for the family
classifier. Not owner data: these are model-written proposals."""

from __future__ import annotations

from typing import Any

PROPOSALS: dict[str, dict[str, Any]] = {
    "gbm_spread_7d": {
        "run": 2,
        "description": (
            "[Machine Learning based Factor] Strictly causal spread-aware"
            " gradient-boosted cross-sectional factor for the 7-day horiz"
            "on. At each close t, compute nine slow features from OHLCV u"
            "p to t: 20d log momentum, 60d log momentum, 60d realized vol"
            "atility, 60d volume trend, 60d log dollar volume, 120d high "
            "proximity, 60d jump-variation ratio, 20d signed-volume imbal"
            "ance, and 20d cross-sectional rank momentum. Winsorize each "
            "feature cross-sectionally at the 1st/99th percentiles and z-"
            "score within day t. Train a 3-class HistGradientBoostingClas"
            "sifier (max_depth=3, learning_rate=0.05, max_iter=200, l2_re"
            "gularization=1.0, min_samples_leaf=50) on the top/middle/bot"
            "tom third of the forward 7-day open-to-open return using an "
            "expanding window ending at m(t)-8, monthly refit, and at lea"
            "st 252 training dates. Output P(top)-P(bottom) ranked cross-"
            "sectionally to [-1,1]. NaN when required windows, cross-sect"
            "ional z-scores, training samples, or model are unavailable."
        ),
        "formulation": (
            "Let r_{i,s}=\\ln(C_{i,s}/C_{i,s-1}). Define raw features at c"
            "lose t: m20_{i,t}=\\ln(C_{i,t}/C_{i,t-20}); m60_{i,t}=\\ln(C_{"
            "i,t}/C_{i,t-60}); vol60_{i,t}=\\sqrt{\\frac{1}{59}\\sum_{k=0}^{"
            "59}(r_{i,t-k}-\\bar r_{i,t})^2}; vt60_{i,t}=\\ln\\left(\\frac{\\f"
            "rac{1}{20}\\sum_{k=0}^{19}V_{i,t-k}}{\\frac{1}{60}\\sum_{k=0}^{"
            "59}V_{i,t-k}}\\right); ldv60_{i,t}=\\ln\\left(\\frac{1}{60}\\sum_"
            "{k=0}^{59}C_{i,t-k}V_{i,t-k}\\right); hp120_{i,t}=\\frac{C_{i,"
            "t}}{\\max_{k=0}^{119}H_{i,t-k}}-1; RV60_{i,t}=\\sum_{k=0}^{59}"
            "r_{i,t-k}^2; BV60_{i,t}=\\frac{\\pi}{2}\\sum_{k=1}^{59}|r_{i,t-"
            "k}||r_{i,t-k+1}|; jv60_{i,t}=\\frac{RV60_{i,t}-BV60_{i,t}}{RV"
            "60_{i,t}}; svi20_{i,t}=\\frac{\\sum_{k=0}^{19}V_{i,t-k}\\,\\math"
            "rm{sign}(C_{i,t-k}-O_{i,t-k})}{\\sum_{k=0}^{19}V_{i,t-k}}; ra"
            "nk\\_mom20_{i,t}=R_{i,t}(m20)-R_{i,t-20}(m20), where R_{i,t}("
            "x) is the cross-sectional percentile rank of x on day t in ["
            "-1,1]. For each day s and feature j, winsorize across availa"
            "ble instruments at the 1st/99th percentiles to get w_{i,s,j}"
            ", then z-score x_{i,s,j}=(w_{i,s,j}-\\mu_{s,j})/\\sigma_{s,j};"
            " NaN if \\sigma_{s,j}=0. Let h=7 and y_{i,s}=\\ln(O_{i,s+8}/O_"
            "{i,s+1}). On each day s, let q_{i,s} be the cross-sectional "
            "percentile rank of y_{i,s} in [0,1] across available instrum"
            "ents; set class c_{i,s}=2 if q_{i,s}>2/3, c_{i,s}=1 if 1/3\\l"
            "e q_{i,s}\\le 2/3, and c_{i,s}=0 if q_{i,s}<1/3. Let m(t) be "
            "the most recent month-start trading day \\le t. Train H_{m(t)"
            "}=HistGradientBoostingClassifier(max_depth=3, learning_rate="
            "0.05, max_iter=200, l2_regularization=1.0, min_samples_leaf="
            "50) on D_{m(t)}=\\{(i,s):s\\le m(t)-8, all x_{i,s,j} and y_{i,"
            "s} available, and at least 252 distinct training dates\\}. At"
            " close t, predict p_{i,t,k}=P(c=k|x_{i,t}) for k=0,1,2 using"
            " H_{m(t)}; set s_{i,t}=p_{i,t,2}-p_{i,t,0}; output f_{i,t}=r"
            "ank_t(s_{i,t}) as the cross-sectional percentile rank in [-1"
            ",1] across available instruments on day t. NaN if any featur"
            "e window is incomplete, a cross-sectional z-score is undefin"
            "ed, fewer than 252 training dates are available, or no model"
            " has been fitted."
        ),
        "variables": {
            "C_{i,s": ("Close price of instrument i on day s (field $close), known at close s."),
            "O_{i,s": (
                "Open price of instrument i on day s (field "
                "$open), used only in the training target."
            ),
            "H_{i,s": ("Daily high price of instrument i on day s (field $high)."),
            "L_{i,s": ("Daily low price of instrument i on day s (field $low)."),
            "V_{i,s": ("Base-asset volume of instrument i on day s (field $volume)."),
            "r_{i,s": ("Daily log return ln(C_{i,s}/C_{i,s-1})."),
            "m20_{i,t": ("20-day log momentum ln(C_{i,t}/C_{i,t-20})."),
            "m60_{i,t": ("60-day log momentum ln(C_{i,t}/C_{i,t-60})."),
            "vol60_{i,t": (
                "60-day realized volatility: sample standard de"
                "viation of the trailing 60 daily log returns."
            ),
            "vt60_{i,t": (
                "60-day volume trend: log ratio of 20-day mean volume to 60-day mean volume."
            ),
            "ldv60_{i,t": (
                "60-day log dollar volume: log of the 60-day mean of close times volume."
            ),
            "hp120_{i,t": ("120-day high proximity: C_{i,t}/max_{k=0..119}H_{i,t-k}-1."),
            "RV60_{i,t": (
                "60-day realized variance: sum of squared da"
                "ily log returns over the trailing 60 days."
            ),
            "BV60_{i,t": (
                "60-day bipower variation: (pi/2) times the sum of adjace"
                "nt absolute-return products over the trailing 60 days."
            ),
            "jv60_{i,t": ("60-day jump-variation ratio: (RV60-BV60)/RV60."),
            "svi20_{i,t": (
                "20-day signed-volume imbalance: volume-weighted si"
                "gn of close-minus-open over the trailing 20 days."
            ),
            "R_{i,t": (
                "Cross-sectional percentile rank operator in ["
                "-1,1] on day t across available instruments."
            ),
            "rank_mom20_{i,t": (
                "20-day cross-sectional rank momentum: R_{i,t}(m20)-R_{i,t-20}(m20)."
            ),
            "W_{1,99}": (
                "Cross-sectional winsorization operator clipping each "
                "feature at its 1st and 99th percentiles on each day."
            ),
            "z_s": ("Cross-sectional z-score operator on day s across available instruments."),
            "x_{i,s,j": (
                "Winsorized and cross-sectionally z-scored feature j for instrument i on day s."
            ),
            "y_{i,s": (
                "Forward 7-day open-to-open log return ln(O_{i,s+8}/O_{i,s"
                "+1}), used only when fully known by the retraining date."
            ),
            "q_{i,s": ("Cross-sectional percentile rank of y_{i,s} in [0,1] on day s."),
            "c_{i,s": (
                "3-class label: 2 for top third, 1 for middle third, 0 for bottom third of q_{i,s}."
            ),
            "m(t)": (
                "Most recent month-start trading day less than or"
                " equal to close t; the model is refit monthly."
            ),
            "D_{m(t)}": (
                "Expanding training set ending at m(t)-8, containing only sam"
                "ples with all features and the fully known 7-day target; req"
                "uires at least 252 distinct training dates."
            ),
            "H_{m(t)}": (
                "3-class HistGradientBoostingClassifier fitted on D_{m(t)} wi"
                "th max_depth=3, learning_rate=0.05, max_iter=200, l2_regular"
                "ization=1.0, min_samples_leaf=50."
            ),
            "p_{i,t,k": ("Predicted probability P(c=k|x_{i,t}) for class k=0,1,2 at close t."),
            "s_{i,t": ("Spread score P(top)-P(bottom)=p_{i,t,2}-p_{i,t,0}."),
            "rank_t": (
                "Cross-sectional percentile rank operator in ["
                "-1,1] across available instruments on day t."
            ),
            "f_{i,t": (
                "Final factor value: cross-sectional rank of s_{i,t}; NaN whe"
                "n data, z-scores, training samples, or model are unavailable"
                "."
            ),
            "h": ("Horizon hyperparameter fixed at 7 trading days."),
            "20": (
                "Lookback window for 20d momentum, volume-trend nume"
                "rator, signed-volume imbalance, and rank momentum."
            ),
            "60": (
                "Lookback window for 60d momentum, realized volatility,"
                " volume trend, log dollar volume, and jump variation."
            ),
            "120": ("Lookback window for high proximity."),
            "252": (
                "Minimum number of distinct training dates required before a model can be fitted."
            ),
            "1/99": ("Cross-sectional winsorization percentiles."),
            "max_depth": ("HistGradientBoostingClassifier hyperparameter fixed at 3."),
            "learning_rate": ("HistGradientBoostingClassifier hyperparameter fixed at 0.05."),
            "max_iter": ("HistGradientBoostingClassifier hyperparameter fixed at 200."),
            "l2_regularization": ("HistGradientBoostingClassifier hyperparameter fixed at 1.0."),
            "min_samples_leaf": ("HistGradientBoostingClassifier hyperparameter fixed at 50."),
        },
    },
    "ml_gbdt_topthird_7d": {
        "run": 2,
        "description": (
            "[Machine Learning based Factor] Strictly causal LightGBM bin"
            "ary classifier for the 7-day horizon. At close t compute onl"
            "y two slow open-family features per coin: long-term reversal"
            " ltr = ln(C_{t-h-L}/C_{t-h}) with h=7 and L=126, positive me"
            "aning past long-term loser; and VWAP distance vwap = C_t / ["
            "sum_{k=0}^{L-1} C_{t-k}V_{t-k} / sum_{k=0}^{L-1} V_{t-k}] - "
            "1 with L=126. Winsorize each feature cross-sectionally at 1/"
            "99 and z-score within day t only. Train a LightGBM binary cl"
            "assifier with num_leaves=7, max_depth=3, learning_rate=0.05,"
            " n_estimators=100, min_child_samples=50, subsample=0.8, cols"
            "ample_bytree=0.8, reg_lambda=1.0 on an expanding window endi"
            "ng at m(t)-h-1, where m(t) is the most recent month-start tr"
            "ading day <= t, requiring at least 252 distinct training dat"
            "es and monthly refit, to predict y=1 if the forward h-day op"
            "en-to-open return ln(O_{s+h+1}/O_{s+1}) is in the cross-sect"
            "ional top third. Output the cross-sectional percentile rank "
            "of predicted probability. Require full L+h windows, no panel"
            "-wide statistics, no residualization, no future data. NaN wh"
            "en required windows, z-scores, training samples, or model ar"
            "e unavailable."
        ),
        "formulation": (
            "Let h=7 and L=126. For instrument i at close t: ltr_{i,t}=\\l"
            "n(C_{i,t-h-L}/C_{i,t-h}); vwap_{i,t}=\\frac{C_{i,t}}{\\frac{\\s"
            "um_{k=0}^{L-1} C_{i,t-k}V_{i,t-k}}{\\sum_{k=0}^{L-1} V_{i,t-k"
            "}}}-1. For each day s and feature j in {ltr,vwap}, winsorize"
            " cross-sectionally at the 1st/99th percentiles: \\tilde{x}_{i"
            ",s,j}=W_{1,99}(x_{i,s,j}); then z-score within day s only: z"
            "_{i,s,j}=(\\tilde{x}_{i,s,j}-\\mu_{j,s})/\\sigma_{j,s}. Target "
            "y_{i,s}=1 if \\ln(O_{i,s+h+1}/O_{i,s+1}) is in the cross-sect"
            "ional top third on day s, else 0. Let m(t) be the most recen"
            "t month-start trading day <= t. Train a LightGBM binary clas"
            "sifier on D_{m(t)}={(i,s): s<=m(t)-h-1, all features and tar"
            "get available, at least 252 distinct training dates} with nu"
            "m_leaves=7, max_depth=3, learning_rate=0.05, n_estimators=10"
            "0, min_child_samples=50, subsample=0.8, colsample_bytree=0.8"
            ", reg_lambda=1.0. Predict p_{i,t}=P(y=1|z_{i,t}). Output f_{"
            "i,t}=\\mathrm{rank}_t(p_{i,t}) as the cross-sectional percent"
            "ile rank of predicted probability across available instrumen"
            "ts on day t. NaN if full L+h windows, z-scores, training sam"
            "ples, or model are unavailable."
        ),
        "variables": {
            "C_{i,s}": ("Close price of instrument i on day s (field $close), known at close s."),
            "O_{i,s}": (
                "Open price of instrument i on day s (field $open), use"
                "d only in the training target and never in features."
            ),
            "V_{i,s}": ("Base-asset volume of instrument i on day s (field $volume)."),
            "h": ("Forward horizon hyperparameter, fixed at 7 trading days."),
            "L": (
                "Slow feature lookback hyperparameter, fixed at 126 trading days for this factor."
            ),
            "ltr_{i,t}": (
                "Long-term reversal feature ln(C_{i,t-h-L}/C_{i"
                ",t-h}); positive means past long-term loser."
            ),
            "vwap_{i,t}": (
                "VWAP distance feature C_{i,t}/[sum_{k=0}^{L-1} C"
                "_{i,t-k}V_{i,t-k}/sum_{k=0}^{L-1} V_{i,t-k}]-1."
            ),
            "W_{1,99}": (
                "Cross-sectional winsorization operator clipping each "
                "feature at its 1st and 99th percentiles on each day."
            ),
            "z_{i,s,j}": (
                "Cross-sectional z-score of feature j on day s across availab"
                "le instruments, computed only from that day's cross-section."
            ),
            "y_{i,s}": (
                "Binary target equal to 1 if forward h-day open-to-open log r"
                "eturn ln(O_{i,s+h+1}/O_{i,s+1}) is in the cross-sectional to"
                "p third on day s, else 0."
            ),
            "m(t)": (
                "Most recent month-start trading day less than "
                "or equal to close t; model refit is monthly."
            ),
            "D_{m(t)}": (
                "Expanding training set ending at m(t)-h-1, containing only s"
                "amples with both z-scored features and fully known target; r"
                "equires at least 252 distinct training dates."
            ),
            "num_leaves": ("LightGBM hyperparameter, fixed at 7."),
            "max_depth": ("LightGBM hyperparameter, fixed at 3."),
            "learning_rate": ("LightGBM hyperparameter, fixed at 0.05."),
            "n_estimators": ("LightGBM hyperparameter, fixed at 100."),
            "min_child_samples": ("LightGBM hyperparameter, fixed at 50."),
            "subsample": ("LightGBM hyperparameter, fixed at 0.8."),
            "colsample_bytree": ("LightGBM hyperparameter, fixed at 0.8."),
            "reg_lambda": ("LightGBM L2 regularization hyperparameter, fixed at 1.0."),
            "min_training_dates": (
                "Minimum number of distinct training dates required before fitting, fixed at 252."
            ),
            "refit_frequency": ("Model refit frequency, fixed at monthly."),
            "p_{i,t}": (
                "Predicted probability of top-third forward return for "
                "instrument i on day t using the model fitted at m(t)."
            ),
            "rank_t": (
                "Cross-sectional percentile rank operator across available instruments on day t."
            ),
            "f_{i,t}": (
                "Final factor value: cross-sectional percentile rank of predi"
                "cted top-third probability; NaN when data, z-scores, trainin"
                "g samples, or model are unavailable."
            ),
        },
    },
    "price_delay_120d": {
        "run": 2,
        "description": (
            "[Information-Diffusion / Price-Delay Factor] Slow price-dela"
            "y measure for each coin, computed as one minus the ratio of "
            "the R-squared from a contemporaneous-market regression to th"
            "e R-squared from a full distributed-lag regression on the eq"
            "ual-weight market return and its first four lags. The regres"
            "sion uses the trailing 120 trading days of daily log returns"
            " ending at close d, requires at least 125 valid daily return"
            "s for the coin and 120 complete regression rows, and uses on"
            "ly returns known by close d. High values indicate that much "
            "of the coin's return variation is explained by lagged market"
            " returns, consistent with slow information diffusion and del"
            "ayed reaction to market-wide news. Decided at close d and in"
            "tended for fill at open d+1. Raw factor; cross-sectional ran"
            "king and sign choice are left to the evaluator."
        ),
        "formulation": (
            "Let \\(r_{i,s}=\\ln(C_{i,s}/C_{i,s-1})\\) be the daily log retu"
            "rn of instrument \\(i\\) on day \\(s\\). Let \\(A_s\\) be the set "
            "of instruments with valid \\(r_{j,s}\\) on day \\(s\\), let \\(N_"
            "s=|A_s|\\), and define the equal-weight market return \\(m_s=\\"
            "frac{1}{N_s}\\sum_{j\\in A_s} r_{j,s}\\), including \\(i\\) if av"
            "ailable. For close day \\(t\\), set the estimation window \\(W_"
            "t=\\{t-119,\\ldots,t\\}\\). For each \\(s\\in W_t\\), require \\(r_{"
            "i,s}\\), \\(m_s\\), \\(m_{s-1}\\), \\(m_{s-2}\\), \\(m_{s-3}\\), and"
            " \\(m_{s-4}\\) to be available, and use the same set of comple"
            "te rows for both regressions below. Estimate the contemporan"
            "eous regression \\(r_{i,s}=\\alpha_0+\\alpha_1 m_s+\\epsilon_s\\)"
            " and define \\(R^2_{contemp,i,t}=1-\\frac{SSR_{contemp}}{SST}\\"
            "). Estimate the full distributed-lag regression \\(r_{i,s}=\\b"
            "eta_0+\\sum_{k=0}^{4}\\beta_k m_{s-k}+\\eta_s\\) and define \\(R^"
            "2_{full,i,t}=1-\\frac{SSR_{full}}{SST}\\), where \\(SST=\\sum_{s"
            "\\in W_t}(r_{i,s}-\\bar{r}_{i,t})^2\\). The factor is \\(f_{i,t}"
            "=1-\\frac{R^2_{contemp,i,t}}{R^2_{full,i,t}}\\). Return NaN if"
            " fewer than 125 valid daily returns for instrument \\(i\\) end"
            "ing at \\(t\\), fewer than 120 complete regression rows in \\(W"
            "_t\\), \\(N_s<2\\) on any required day, \\(SST=0\\), or \\(R^2_{fu"
            "ll,i,t}\\le 10^{-12}\\)."
        ),
        "variables": {
            "C_{i,s}": (
                "Close price of instrument i on day s (field $close), known at the close of day s."
            ),
            "r_{i,s}": (
                "Daily log return of instrument i on day s, defined as ln(C_{i,s}/C_{i,s-1})."
            ),
            "A_s": ("Set of instruments with a valid daily log return on day s."),
            "N_s": (
                "Number of instruments in A_s; must be at least 2 on"
                " each day used for the equal-weight market return."
            ),
            "m_s": (
                "Equal-weight market log return on day s, computed as the av"
                "erage of r_{j,s} over j in A_s, including i if available."
            ),
            "t": ("Current close day d; the factor is known at the close of day t."),
            "W_t": ("Trailing 120-trading-day estimation window {t-119, ..., t}."),
            "120": (
                "Regression estimation window length in tra"
                "ding days (hyperparameter, fixed at 120)."
            ),
            "4": (
                "Number of market-return lags included in the f"
                "ull regression (hyperparameter, fixed at 4)."
            ),
            "125": (
                "Minimum number of valid daily log returns required for"
                " the coin ending at t (hyperparameter, fixed at 125)."
            ),
            "R^2_{contemp,i,t}": (
                "R-squared from regressing r_{i,s} on the contemporaneous mar"
                "ket return m_s over the common complete estimation rows in W"
                "_t."
            ),
            "R^2_{full,i,t}": (
                "R-squared from regressing r_{i,s} on m_s and its first four "
                "lags m_{s-1}, m_{s-2}, m_{s-3}, m_{s-4} over the same common"
                " complete estimation rows in W_t."
            ),
            "SSR_{contemp}": ("Sum of squared residuals from the contemporaneous regression."),
            "SSR_{full}": ("Sum of squared residuals from the full distributed-lag regression."),
            "SST": (
                "Total sum of squares of r_{i,s} around its mean over the common estimation rows."
            ),
            "10^{-12}": (
                "Small epsilon used to guard the denominator R^2"
                "_{full,i,t} against zero or near-zero values."
            ),
            "f_{i,t}": (
                "Price-delay factor for instrument i on day t; larger values "
                "indicate more return variation explained by lagged market re"
                "turns. NaN when the required returns, complete regression ro"
                "ws, market breadth, or non-degenerate R-squared are unavaila"
                "ble."
            ),
        },
    },
    "ml_logit_top3_diffusion_7d": {
        "run": 3,
        "description": (
            "[Machine Learning based Factor] Strictly causal cross-sectio"
            "nal L2 logistic-regression composite for the 7-day horizon. "
            "At each close t, six slow information-diffusion/path-complex"
            "ity features are computed from OHLCV data up to t: price_del"
            "ay_120d, lead_lag_score_120d, lag_lag_score_120d, delay_beta"
            "_ratio_120d, hurst_120d, and entropy_120d. Each feature is z"
            "-scored only within day t's cross-section. An L2 logistic re"
            "gression with alpha=1.0 is trained to predict whether the fo"
            "rward 7-day open-to-open log return ln(O_{s+8}/O_{s+1}) is i"
            "n the cross-sectional top third on day s, using an expanding"
            " window ending at m(t)-8, where m(t) is the most recent mont"
            "h-start trading day <= t; the model is refit monthly and req"
            "uires at least 252 distinct training dates. The output is th"
            "e cross-sectional percentile rank of the predicted top-third"
            " probability on day t. No panel-wide statistics, no residual"
            "ization, and no future data are used. NaN when required wind"
            "ows, cross-sectional z-scores, training samples, both target"
            " classes, or model coefficients are unavailable."
        ),
        "formulation": (
            "Let r_{i,s}=\\ln(C_{i,s}/C_{i,s-1}). Let A_s be the set of in"
            "struments with valid r_{j,s} on day s, N_s=|A_s|, and m_s=\\f"
            "rac{1}{N_s}\\sum_{j\\in A_s} r_{j,s}. For close t set W_t=\\{t-"
            "119,\\ldots,t\\}. For price_delay and delay_beta_ratio, requir"
            "e common complete rows s\\in W_t with r_{i,s}, m_s, m_{s-1}, "
            "m_{s-2}, m_{s-3}, m_{s-4} available. Estimate r_{i,s}=\\alpha"
            "_0+\\alpha_1 m_s+\\epsilon_s and set R^2_{contemp,i,t}=1-\\frac"
            "{SSR_{contemp}}{SST}. Estimate r_{i,s}=\\beta_0+\\sum_{k=0}^{4"
            "}\\beta_k m_{s-k}+\\eta_s and set R^2_{full,i,t}=1-\\frac{SSR_{"
            "full}}{SST}, where SST=\\sum_{s\\in W_t}(r_{i,s}-\\bar r_{i,t})"
            "^2. Define price_delay_{i,t}=1-\\frac{R^2_{contemp,i,t}}{R^2_"
            "{full,i,t}} and delay_beta_ratio_{i,t}=\\frac{\\sum_{k=1}^{4}|"
            "\\beta_k|}{|\\beta_0|+\\sum_{k=1}^{4}|\\beta_k|}. Define lead_la"
            "g_score_{i,t}=\\operatorname{corr}(\\{r_{i,s}\\}_{s=t-119}^{t-1"
            "},\\{m_{s+1}\\}_{s=t-119}^{t-1}) and lag_lag_score_{i,t}=\\oper"
            "atorname{corr}(\\{r_{i,s}\\}_{s=t-119}^{t-1},\\{m_{s-1}\\}_{s=t-"
            "119}^{t-1}). For hurst, for q\\in\\{1,2,4,8,16\\} form R^{(q)}_"
            "{i,t,m}=\\sum_{j=0}^{q-1} r_{i,t-119+mq+j} for m=0,\\ldots,\\lf"
            "loor120/q\\rfloor-1 from the trailing 120 daily returns; let "
            "Var^{(q)}_{i,t} be their sample variance. Regress \\ln Var^{("
            "q)}_{i,t} on \\ln q over available q with Var^{(q)}_{i,t}>0 a"
            "nd set hurst_{i,t}=0.5\\hat{\\gamma}, where \\hat{\\gamma} is th"
            "e slope. For entropy, let a_{i,t}=\\min_{k=0}^{119}r_{i,t-k} "
            "and b_{i,t}=\\max_{k=0}^{119}r_{i,t-k}; if b_{i,t}-a_{i,t}>10"
            "^{-12}, set 5 equal-width bins e_k=a_{i,t}+k(b_{i,t}-a_{i,t}"
            ")/5, counts n_b, p_b=n_b/120, and entropy_{i,t}=-\\sum_{b=1}^"
            "{5}p_b\\ln p_b. For each day s and feature j, z_{i,s,j}=(x_{i"
            ",s,j}-\\mu_{j,s})/\\sigma_{j,s} across available instruments. "
            "Let h=7. Target y_{i,s}=1 if the cross-sectional percentile "
            "rank of y_raw_{i,s}=\\ln(O_{i,s+h+1}/O_{i,s+1}) on day s is a"
            "t least 2/3, else 0. Let m(t) be the most recent month-start"
            " trading day <= t. Train L2 logistic regression on D_{m(t)}="
            "\\{(i,s): s\\le m(t)-h-1, all six z-features and y available, "
            "at least 252 distinct dates\\}: \\hat\\theta_{m(t)}=\\arg\\min_{b"
            "_0,\\beta}\\sum_{(i,s)\\in D_{m(t)}}\\left[-y_{i,s}\\ln p_{i,s}-("
            "1-y_{i,s})\\ln(1-p_{i,s})\\right]+1.0\\sum_j\\beta_j^2, with p_{"
            "i,s}=1/(1+\\exp(-(b_0+x_{i,s}^T\\beta))). Predict p_{i,t}=1/(1"
            "+\\exp(-(b_{0,m(t)}+x_{i,t}^T\\beta_{m(t)}))). Output f_{i,t}="
            "\\operatorname{rank}_t(p_{i,t}) as the cross-sectional percen"
            "tile rank in [-1,1] across available instruments on day t. N"
            "aN if any feature window is incomplete, z-score undefined, f"
            "ewer than 2 instruments, fewer than 252 training dates, only"
            " one target class, no model, or target not fully known."
        ),
        "variables": {
            "C_{i,s}": ("Close price of instrument i on day s (field $close), known at close s."),
            "O_{i,s}": (
                "Open price of instrument i on day s (field $open), use"
                "d only in the training target and never in features."
            ),
            "r_{i,s}": ("Daily log return ln(C_{i,s}/C_{i,s-1})."),
            "A_s": ("Set of instruments with valid daily log return on day s."),
            "N_s": (
                "Number of instruments in A_s; must be at least 2 on"
                " each day used for the equal-weight market return."
            ),
            "m_s": ("Equal-weight market log return on day s, average of r_{j,s} over j in A_s."),
            "t": ("Current close day d; factor known at close t."),
            "W_t": ("Trailing 120-trading-day estimation window {t-119,...,t}."),
            "120": (
                "Lookback window length in trading days for price_delay, dela"
                "y_beta_ratio, lead_lag_score, lag_lag_score, hurst, and entr"
                "opy (hyperparameter, fixed at 120)."
            ),
            "4": (
                "Number of market-return lags in the full distribu"
                "ted-lag regression (hyperparameter, fixed at 4)."
            ),
            "R^2_{contemp,i,t}": (
                "R-squared from contemporaneous regression of r_"
                "{i,s} on m_s over common complete rows in W_t."
            ),
            "R^2_{full,i,t}": (
                "R-squared from full distributed-lag regression of r_{i,s} on"
                " m_s and its first four lags over the same common complete r"
                "ows; must exceed 1e-12."
            ),
            "SSR_{contemp}": ("Sum of squared residuals from contemporaneous regression."),
            "SSR_{full}": ("Sum of squared residuals from full distributed-lag regression."),
            "SST": ("Total sum of squares of r_{i,s} around its mean over common estimation rows."),
            "price_delay_{i,t}": ("Price-delay feature 1 - R^2_contemp/R^2_full."),
            "delay_beta_ratio_{i,t}": (
                "Ratio of sum of absolute lagged market coefficients to sum o"
                "f absolute contemporaneous and lagged market coefficients fr"
                "om the full regression."
            ),
            "lead_lag_score_{i,t}": (
                "Correlation between r_{i,s} and m_{s+1} over s=t-119,...,t-1."
            ),
            "lag_lag_score_{i,t}": (
                "Correlation between r_{i,s} and m_{s-1} over s=t-119,...,t-1."
            ),
            "hurst_{i,t}": (
                "Aggregated-variance Hurst exponent from trailing 120 daily l"
                "og returns using q in {1,2,4,8,16}; slope of ln Var(q-day re"
                "turn) on ln q divided by 2."
            ),
            "entropy_{i,t}": (
                "Shannon entropy of 5-bin equal-width distri"
                "bution of trailing 120 daily log returns."
            ),
            "x_{i,s,j}": (
                "The j-th raw feature for instrument i on day s before cross-sectional z-scoring."
            ),
            "z_{i,s,j}": (
                "Cross-sectional z-score of feature j on day s across availab"
                "le instruments; computed only from that day's cross-section."
            ),
            "mu_{j,s}": ("Cross-sectional mean of feature j on day s."),
            "sigma_{j,s}": ("Cross-sectional standard deviation of feature j on day s."),
            "y_raw_{i,s}": (
                "Forward h-day open-to-open log return ln(O_{i,s+h+1}/O_{i,"
                "s+1}) used only when fully known by the retraining date."
            ),
            "y_{i,s}": (
                "Binary top-third target: 1 if y_raw_{i,s} is in "
                "the cross-sectional top third on day s, else 0."
            ),
            "h": ("Horizon hyperparameter fixed at 7 trading days for this factor."),
            "8": (
                "Target lag h+1 used in ln(O_{i,s+8}/O_{i,s+1}) and in the training cutoff m(t)-8."
            ),
            "m(t)": (
                "Most recent month-start trading day less tha"
                "n or equal to close t; model refit monthly."
            ),
            "D_{m(t)}": (
                "Expanding training set ending at m(t)-h-1, containing only s"
                "amples with all six z-features and the fully known target; r"
                "equires at least 252 distinct training dates and both target"
                " classes."
            ),
            "alpha": (
                "L2 regularization strength on slope coeffici"
                "ents, fixed at 1.0; intercept unpenalized."
            ),
            "p_{i,s}": ("Logistic probability of top-third membership for sample (i,s)."),
            "p_{i,t}": (
                "Predicted top-third probability for instrumen"
                "t i on day t using the model fitted at m(t)."
            ),
            "rank_t": (
                "Cross-sectional percentile rank operator in ["
                "-1,1] across available instruments on day t."
            ),
            "f_{i,t}": (
                "Final factor value: cross-sectional rank of predicted top-th"
                "ird probability; NaN when data, z-scores, training samples, "
                "both classes, or model coefficients are unavailable."
            ),
            "10^{-12}": (
                "Small epsilon used to guard the entropy bin-width check and R-squared denominator."
            ),
            "252": (
                "Minimum number of distinct training dates required before a model can be fitted."
            ),
            "2/3": ("Top-third threshold on the cross-sectional percentile rank of y_raw."),
            "5": ("Number of bins for the return-distribution entropy feature."),
            "1.0": ("L2 logistic regression penalty hyperparameter alpha."),
        },
    },
    "ml_logit_topthird_weekly_open": {
        "run": 3,
        "description": (
            "[Machine Learning based Factor] Strictly causal cross-sectio"
            "nal L2 logistic top-third classifier for the weekly horizon."
            " At each close t, compute five open-family features from OHL"
            "CV data up to t: ltr_189d_skip21d, max_drawdown_252d, vwap_d"
            "istance_189d_skip21d excluding the last 21 days, overnight_d"
            "rift_60d, and variance_ratio_5_120d. Winsorize each feature "
            "cross-sectionally at the 1st/99th percentiles within day t, "
            "then z-score within day t. Train an L2 logistic regression w"
            "ith C=1.0 on an expanding window of samples whose forward 7-"
            "day open-to-open return label is fully known by the most rec"
            "ent month-start retraining date m(t), i.e. s <= m(t)-8, with"
            " at least 252 distinct training dates and monthly refit. The"
            " label is top-third membership of the forward 7-day open-to-"
            "open return among available instruments on day s. Output the"
            " cross-sectional percentile rank of the predicted probabilit"
            "y on day t. NaN when required feature windows, cross-section"
            "al z-scores, training samples, model coefficients, or labels"
            " are unavailable."
        ),
        "formulation": (
            "Let r_{i,u}=\\ln(C_{i,u}/C_{i,u-1}). At close s define raw fe"
            "atures: x1_{i,s}=-\\sum_{u=s-209}^{s-21} r_{i,u}; x2_{i,s}=\\m"
            "ax_{0\\le a<b\\le251}\\frac{C_{i,s-251+a}-C_{i,s-251+b}}{C_{i,s"
            "-251+a}}; x3_{i,s}=\\frac{C_{i,s}}{\\frac{\\sum_{k=21}^{209} C_"
            "{i,s-k}V_{i,s-k}}{\\sum_{k=21}^{209} V_{i,s-k}}}-1; x4_{i,s}="
            "\\frac{1}{60}\\sum_{k=0}^{59}\\ln\\left(\\frac{O_{i,s-k}}{C_{i,s-"
            "k-1}}\\right); Var_{d,i,s}=\\frac{1}{119}\\sum_{k=0}^{119}(r_{i"
            ",s-k}-\\bar r_{i,s})^2; R_{i,m,s}=\\sum_{j=0}^{4} r_{i,s-119+5"
            "m+j}, m=0,\\ldots,23; Var_{5,i,s}=\\frac{1}{23}\\sum_{m=0}^{23}"
            "(R_{i,m,s}-\\bar R_{i,s})^2; x5_{i,s}=\\frac{Var_{5,i,s}}{5 Va"
            "r_{d,i,s}}-1. For each day s and feature j=1..5, winsorize c"
            "ross-sectionally at the 1st/99th percentiles and z-score: \\t"
            "ilde x_{i,s,j}=z_s(W_{1,99}(x_{i,s,j})). Label at close s: y"
            "_{i,s}=1 if the forward 7-day open-to-open log return F_{i,s"
            "}=\\ln(O_{i,s+8}/O_{i,s+1}) is in the top third of the cross-"
            "section of available instruments on day s, else 0. Let m(t) "
            "be the most recent month-start trading day \\le t. Train an L"
            "2-penalized logistic regression with inverse regularization "
            "C=1.0 on D_{m(t)}=\\{(i,s): s\\le m(t)-8, all five \\tilde x an"
            "d y available, at least 252 distinct training dates\\}: p_{i,"
            "s}=\\sigma(b_0+\\tilde x_{i,s}^T\\beta), \\hat\\theta_{m(t)}=\\arg"
            "\\min_{b_0,\\beta}-\\sum_{(i,s)\\in D_{m(t)}}[y_{i,s}\\ln p_{i,s}"
            "+(1-y_{i,s})\\ln(1-p_{i,s})]+\\frac{1}{2C}\\sum_j\\beta_j^2. Pre"
            "dict p_{i,t}=\\sigma(b_{0,m(t)}+\\tilde x_{i,t}^T\\beta_{m(t)})"
            ". Output f_{i,t}=rank_t(p_{i,t}) as the cross-sectional perc"
            "entile rank in [-1,1] across available instruments on day t."
            " NaN if any feature window is incomplete, z-score or rank is"
            " undefined, fewer than 2 instruments are available, fewer th"
            "an 252 distinct training dates, no model, or label not fully"
            " known."
        ),
        "variables": {
            "C_i_u": ("Close price of instrument i on day u (field $close), known at close u."),
            "O_i_u": ("Open price of instrument i on day u (field $open), known at close u."),
            "V_i_u": ("Base-asset volume of instrument i on day u (field $volume)."),
            "r_i_u": ("Daily log return ln(C_i_u/C_i_u-1)."),
            "x1_i_s": (
                "ltr_189d_skip21d: negative cumulative 189-day lo"
                "g return ending 21 trading days before close s."
            ),
            "x2_i_s": (
                "max_drawdown_252d: maximum peak-to-trough close drawdown ov"
                "er the trailing 252 trading days, as a positive magnitude."
            ),
            "x3_i_s": (
                "vwap_distance_189d_skip21d: current close divided by the 189"
                "-day volume-weighted average close ending 21 days before s, "
                "minus one."
            ),
            "x4_i_s": (
                "overnight_drift_60d: mean overnight log return ln(O/C"
                " previous close) over the trailing 60 trading days."
            ),
            "x5_i_s": (
                "variance_ratio_5_120d: variance of 24 non-overlapping 5-day "
                "log returns divided by 5 times the variance of 120 daily log"
                " returns, minus one."
            ),
            "W_1_99": (
                "Cross-sectional winsorization operator clipping each "
                "feature at its 1st and 99th percentiles on each day."
            ),
            "z_s": ("Cross-sectional z-score operator on day s across available instruments."),
            "tilde_x_i_s_j": (
                "Winsorized and cross-sectionally z-scored feature j for instrument i on day s."
            ),
            "F_i_s": (
                "Forward 7-day open-to-open log return ln(O_i_s+8/O_i_s"
                "+1), used only for training labels when fully known."
            ),
            "y_i_s": (
                "Binary top-third label: 1 if F_i_s is in the highest "
                "third among available instruments on day s, else 0."
            ),
            "m_t": (
                "Most recent month-start trading day less than or"
                " equal to close t; the model is refit monthly."
            ),
            "D_m_t": (
                "Expanding training set ending at m(t)-8, containing samples "
                "with all five z-features and the fully known 7-day label; re"
                "quires at least 252 distinct training dates."
            ),
            "C": ("Inverse L2 regularization strength for logistic regression, fixed at 1.0."),
            "sigma": "Logistic sigmoid function.",
            "b_0": "Logistic regression intercept.",
            "beta": ("Vector of five logistic regression slope coefficients."),
            "p_i_s": ("Predicted top-third probability for training sample (i,s)."),
            "p_i_t": (
                "Predicted top-third probability for instrument"
                " i at close t using the model fitted at m(t)."
            ),
            "rank_t": (
                "Cross-sectional percentile rank operator in ["
                "-1,1] across available instruments on day t."
            ),
            "f_i_t": (
                "Final factor value: cross-sectional rank of predicted top-th"
                "ird probability; NaN when data, z-scores, training samples, "
                "or model coefficients are unavailable."
            ),
            "189": ("Lookback length for ltr_189d_skip21d and vwap_distance_189d_skip21d."),
            "21": (
                "Skip period in trading days for ltr_189d_skip21d and vwap_distance_189d_skip21d."
            ),
            "252": ("Drawdown lookback length and minimum number of distinct training dates."),
            "60": ("Overnight-drift lookback length."),
            "120": ("Variance-ratio daily-return window length."),
            "5": ("Variance-ratio aggregation horizon."),
            "24": ("Number of non-overlapping 5-day returns in the 120-day variance-ratio window."),
            "1/99": ("Cross-sectional winsorization percentiles."),
            "7": ("Forward label horizon in trading days: open s+1 to open s+8."),
            "8": (
                "Embargo/lag in trading days used to ensure the"
                " 7-day forward label is fully known by m(t)."
            ),
        },
    },
    "cs_ridge_openfam_7d": {
        "run": 3,
        "description": (
            "[Machine Learning based Factor] Strictly causal walk-forward"
            " cross-sectional ridge regression on seven per-day cross-sec"
            "tionally z-scored open-family features, predicting the cross"
            "-sectional rank of the forward 7-day open-to-open return. Al"
            "pha=10, expanding training window ending at m(t)-8, minimum "
            "252 distinct dates, monthly refit. Output is the cross-secti"
            "onal percentile rank of the prediction. No panel-wide statis"
            "tics, no residualization, and no future data are used. Decid"
            "ed at close t and intended for fill at open t+1. NaN if any "
            "feature window is incomplete, z-score undefined, fewer than "
            "2 instruments, fewer than 252 training dates, no model, or t"
            "arget not fully known."
        ),
        "formulation": (
            "Let r_{i,s}=\\ln(C_{i,s}/C_{i,s-1}). Define raw features LTR1"
            "89_{i,t}=-\\sum_{s=t-209}^{t-21} r_{i,s}, LTR252_{i,t}=-\\sum_"
            "{s=t-279}^{t-28} r_{i,s}, MDD252_{i,t}=\\max_{0\\le a<b\\le 251"
            "}(C_{i,t-251+a}-C_{i,t-251+b})/C_{i,t-251+a}, VWAP189_{i,t}="
            "C_{i,t}/[\\sum_{k=21}^{209}C_{i,t-k}V_{i,t-k}/\\sum_{k=21}^{20"
            "9}V_{i,t-k}]-1, ON60_{i,t}=(1/60)\\sum_{k=0}^{59}\\ln(O_{i,t-k"
            "}/C_{i,t-k-1}), ID60_{i,t}=(1/60)\\sum_{k=0}^{59}\\ln(C_{i,t-k"
            "}/O_{i,t-k}), and VR5_{i,t}=Var_5/(5\\,Var_d)-1, where Var_d="
            "(1/119)\\sum_{k=0}^{119}(r_{i,t-k}-\\bar r_{i,t})^2, R_{i,m,t}"
            "=\\sum_{j=0}^{4}r_{i,t-119+5m+j} for m=0,\\ldots,23, and Var_5"
            "=(1/23)\\sum_{m=0}^{23}(R_{i,m,t}-\\bar R_{i,t})^2. For each d"
            "ay s and feature j, compute z_{i,s,j}=(x_{i,s,j}-\\mu_{j,s})/"
            "\\sigma_{j,s} across available instruments on day s. Let y_{i"
            ",s}=rank_s(\\ln(O_{i,s+8}/O_{i,s+1})) be the cross-sectional "
            "percentile rank in [-1,1]. Let m(t) be the most recent month"
            "-start trading day <= t. Train ridge on D_{m(t)}=\\{(i,s): s\\"
            "le m(t)-8,\\ s\\in[\\text{earliest available},m(t)-8],\\ \\text{a"
            "ll seven z-features and }y\\text{ available}\\} with at least "
            "252 distinct dates: (\\hat b_0,\\hat\\beta)=\\arg\\min_{b_0,\\beta"
            "}\\sum_{(i,s)\\in D_{m(t)}}(y_{i,s}-b_0-\\sum_{j=1}^{7}z_{i,s,j"
            "}\\beta_j)^2+10\\sum_{j=1}^{7}\\beta_j^2, with unpenalized inte"
            "rcept b_0. Predict \\hat y_{i,t}=\\hat b_0+\\sum_{j=1}^{7}z_{i,"
            "t,j}\\hat\\beta_j. Output f_{i,t}=rank_t(\\hat y_{i,t}) as the "
            "cross-sectional percentile rank in [-1,1] across available i"
            "nstruments on day t."
        ),
        "variables": {
            "C_{i,s}": ("Close price of instrument i on day s (field $close), known at close s."),
            "O_{i,s}": (
                "Open price of instrument i on day s (field $open), use"
                "d only in the training target and never in features."
            ),
            "V_{i,s}": ("Base-asset volume of instrument i on day s (field $volume)."),
            "r_{i,s}": ("Daily log return ln(C_{i,s}/C_{i,s-1})."),
            "LTR189_{i,t}": ("Negative 189-day cumulative log return ending 21 days before t."),
            "LTR252_{i,t}": ("Negative 252-day cumulative log return ending 28 days before t."),
            "MDD252_{i,t}": (
                "Maximum peak-to-trough close drawdown over the tra"
                "iling 252 trading days, as a positive magnitude."
            ),
            "VWAP189_{i,t}": (
                "Close relative to the 189-day volume-weighted avera"
                "ge close over days t-209 through t-21, minus one."
            ),
            "ON60_{i,t}": ("Mean overnight log return over the trailing 60 trading days."),
            "ID60_{i,t}": ("Mean intraday log return over the trailing 60 trading days."),
            "VR5_{i,t}": (
                "Variance ratio of 5-day non-overlapping log returns to daily"
                " log returns over the trailing 120 daily returns, minus one."
            ),
            "Var_d": (
                "Sample variance of the trailing 120 daily log returns, using denominator 119."
            ),
            "Var_5": (
                "Sample variance of the 24 non-overlapping 5-day log returns, using denominator 23."
            ),
            "R_{i,m,t}": (
                "m-th non-overlapping 5-day log return over the"
                " trailing 120 daily returns, for m=0,...,23."
            ),
            "x_{i,s,j}": (
                "The j-th raw feature for instrument i on day s before cross-sectional z-scoring."
            ),
            "z_{i,s,j}": (
                "Cross-sectional z-score of feature j on day s across availab"
                "le instruments; computed only from that day's cross-section."
            ),
            "\\mu_{j,s}": (
                "Cross-sectional mean of feature j on day s across available instruments."
            ),
            "\\sigma_{j,s}": (
                "Cross-sectional sample standard deviation of feature j on da"
                "y s across available instruments, using denominator N_s-1."
            ),
            "N_s": (
                "Number of available instruments with valid data on d"
                "ay s; must be at least 2 for z-scoring and ranking."
            ),
            "y_{i,s}": (
                "Cross-sectional percentile rank in [-1,1] of the forward 7-d"
                "ay open-to-open log return ln(O_{i,s+8}/O_{i,s+1}), used onl"
                "y when fully known by the retraining date."
            ),
            "rank_s": (
                "Cross-sectional percentile rank operator mapping valu"
                "es to [-1,1] across available instruments on day s."
            ),
            "m(t)": (
                "Most recent month-start trading day less than or"
                " equal to close t; the model is refit monthly."
            ),
            "D_{m(t)}": (
                "Expanding training set ending at m(t)-8, containing only sam"
                "ples with all seven z-features and the fully known 7-day tar"
                "get; requires at least 252 distinct training dates."
            ),
            "alpha": (
                "Ridge penalty hyperparameter on slope coeffici"
                "ents, fixed at 10; intercept is unpenalized."
            ),
            "b_0": ("Unpenalized intercept of the ridge regression."),
            "\\beta": ("Vector of seven ridge-regression slope coefficients."),
            "\\hat y_{i,t}": (
                "Predicted forward 7-day log-return rank for instr"
                "ument i on day t using the model fitted at m(t)."
            ),
            "f_{i,t}": (
                "Final factor value: cross-sectional percentile rank of the p"
                "redicted 7-day return; NaN when data, z-scores, training sam"
                "ples, or model coefficients are unavailable."
            ),
            "7": ("Target horizon in trading days: open s+1 to open s+8."),
            "8": (
                "Target lag/skip in trading days used to ensure t"
                "he 7-day forward return is fully known by m(t)."
            ),
            "189": ("Long-term reversal and VWAP lookback window length in trading days."),
            "21": ("Skip period in trading days for the 189-day reversal and VWAP features."),
            "252": (
                "Long-term reversal and maximum-drawdown lookback window length in trading days."
            ),
            "28": ("Skip period in trading days for the 252-day reversal feature."),
            "60": ("Overnight and intraday drift averaging window length in trading days."),
            "120": ("Variance-ratio daily-return window length in trading days."),
            "5": ("Variance-ratio aggregation horizon in trading days."),
            "24": ("Number of non-overlapping 5-day returns inside the 120-day window."),
            "252_min_dates": (
                "Minimum number of distinct training dates required before a model can be fitted."
            ),
        },
    },
}
