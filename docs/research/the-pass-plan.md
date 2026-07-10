# The Pass: plan pro testovani trading strategii a automatizaci

Datum: 2026-07-09

Status: strategicky plan, nezavisly na aktualnim stavu repozitare. Dokument popisuje cilovy
system a gate-based cestu k nemu. Nejedna se o schvaleni live tradingu.

Nazev `The Pass` je z kuchynskeho prostredi: je to misto, kde hotove jidlo projde
posledni kontrolou pred vydajem. V tomto projektu je "jidlo" strategie, "recept" je
`StrategySpec`, "vareni" je backtest/replay a "vydaj" je paper nebo live review. Nic se
neposila dal bez dukazu.

## 1. Zamer

Chceme postavit "sous-chef pro trading research": system, ktery z napadu na strategii udela
formalni hypotezu, sebere a overi data, implementuje backtest, nezavisle ho zkritizuje,
spocita robustnost, otestuje realne naklady, pusti paper trading a teprve po splneni predem
danych bran vyrobi automatizaci. System musi fungovat pro crypto, futures, prediction
markets a pozdeji dalsi trhy, ale nesmi predstirat, ze jeden backtest je dukaz edge.

Hlavni princip: worker muze psat kod a spoustet experimenty, ale nesmi sam rozhodovat, ze
strategie je dobra. Orchestrator drzi evidenci, brany, nezavisly review a opakovatelne
vystupy. Tvrzeni bez logu, dataset fingerprintu, cost modelu a out-of-sample evidence nema
vahu.

## 2. Inspirace ze sous-chef

`tomascupr/sous-chef` je uzitecny vzor ne kvuli nazvoslovi, ale kvuli delbe odpovednosti:

- Orchestrator planuje, pise ticket, kontroluje diff a znovu spousti overeni.
- Worker implementuje, ale nema posledni slovo.
- Pro goal-shaped praci existuje smycka, ktera bezi do splneni meritelneho prikazu nebo do
  budget/kill limitu.
- Rozhodnuti maji "receipts": zdroj, duvod, vystup, naklad, verdikt.
- Standing rules patri do jedineho sdileneho dokumentu; per-task instrukce patri do ticketu.

Pro trading to prekladame takto:

- Drahy agent je Head Researcher / Risk Judge, ne generator nahodnych strategii.
- Levnejsi workeri delaji ingest, implementaci, parametricke sweepy, reporty a refaktory.
- Nezavisly reviewer hleda data leakage, lookahead bias, survivorship bias, spatne fees,
  overfitting, spatne timestampy, chybejici vyplne a nereprodukivni vysledky.
- Kazdy run vytvari auditni balicek: spec, data manifest, kodovy commit/hash, metriky,
  grafy, cost model, rizika, verdikt, dalsi krok.

## 3. Core thesis

Trading strategy lab musi optimalizovat pro preziti, ne pro krasne equity krivky.
Hlavni produkt systemu neni "strategie", ale disciplinovany proces, ktery levne zabiji
spatne napady a pusti dal jen ty, ktere preziji:

- predregistraci hypotezy,
- datovou kontrolu,
- realisticky execution model,
- walk-forward nebo purged/CPCV validaci,
- multiple-testing korekce,
- stresove scenare,
- paper trading,
- risk review,
- explicitni lidske schvaleni pro live.

## 4. Non-negotiable pravidla

- Zadny live trading ani real order placement bez explicitniho lidskeho schvaleni.
- Zadna strategie nepostupuje, pokud nema predem napsany `StrategySpec`.
- Zadny model nesmi trenovat na budoucnosti ani na timestampove nejasnych datech.
- Zadny vysledek bez zapocitani fees, spreadu, slippage, funding/borrow, latency a fill risku.
- Zadny "best parameter" bez evidence o mnozstvi zkousenych variant.
- Zadna metrika sama o sobe nerozhoduje; Sharpe bez drawdownu, tail risku a turnoveru je
  nedostatecny.
- Zadna automatizace nesmi menit kapital, leverage, trhy nebo order typy mimo schvalenou
  konfiguraci.
- Kazdy agenticky vystup musi byt reprodukovatelny prikazem nebo artefaktem.

## 5. Zakladni architektura

System rozdelime na osm vrstev. Kazda vrstva ma vlastni vstupy, vystupy a brany.

### 5.1 Research intake

Ucel: prevest textovy napad na formalni hypotezu.

Vstupy:

- studie, knihy, interview, vlastni pozorovani,
- trzni anomalii nebo mechanicky signal,
- cilovy trh a instrumenty,
- casovy horizont,
- predpokladany zdroj edge.

Vystup: `StrategySpec` v YAML/JSON.

Povinne pole:

- `hypothesis`: proc by mela existovat ekonomicka nebo mikrostrukturni pricina zisku,
- `market`: venue, instrument, trading hours, settlement, collateral, margin,
- `signal`: vstupni data, transformace, latence, cas rozhodnuti,
- `execution`: order typy, limit/market pravidla, max participation, cancel pravidla,
- `costs`: fees, spread, slippage, impact, funding, borrow, taxes, gas, failed tx,
- `risk`: position sizing, leverage, stop, portfolio exposure, max drawdown, kill switch,
- `validation`: train/test rezim, embargo, holdout, stress, expected failure modes,
- `done_when`: presne gate metriky,
- `kill_when`: presne duvody, kdy napad konci.

### 5.2 Data layer

Ucel: mit pravdiva, casove zarovnana a auditovatelna data.

Komponenty:

- raw immutable store: puvodni tick/orderbook/bar/funding/news/sentiment eventy,
- normalized store: jednotny schema model pro instrumenty a eventy,
- feature store: deterministicky vypocitane features s versioningem,
- data manifest: fingerprint datasetu, casovy rozsah, missing data, outliery, timezone,
  corporate actions/contract rolls, exchange status, latency pozorovani.

Minimalni schema:

- `instrument`: symbol, venue, asset class, tick size, lot size, contract multiplier,
  margin mode, quote currency, expiry nebo perpetual flag,
- `market_data_event`: event time, receive time, source time, sequence id, bid/ask/depth,
  trade price/size, open interest, funding, mark/index price,
- `decision_event`: strategy id, model version, feature snapshot id, intended action,
- `order_event`: created, sent, acked, partially filled, filled, canceled, rejected,
- `portfolio_event`: exposure, margin, PnL, realized/unrealized, fees, cash/collateral.

Gate:

- Zadny backtest na datech bez manifestu.
- Zadny intraday system bez rozdilu `event_time`, `receive_time`, `decision_time`.
- Zadny futures/crypto perp test bez funding/mark/index price dat, pokud drzi pozice pres
  funding interval.

### 5.3 Strategy research engine

Ucel: rychle zabijet spatne napady.

Rezimy:

- vectorized screen pro jednoduche signal/parameter sweepy,
- event-driven backtest pro kazdeho kandidata, ktery projde screenem,
- replay mode pro tick/orderbook/fill simulaci,
- paper mode se stejnym rozhodovacim kodem jako backtest,
- live mode pouze za manualnim approval gate.

Doporuceny technicky pristup:

- Ridit se rozhodnutim v sekci 19.4.
- Core framework je engine-neutral; konkretni adapter muze pouzit pandas/NumPy, vectorbt,
  NautilusTrader, Backtrader, LEAN nebo vlastni simulator, pokud emituje povinne artefakty.
- Public examples mohou pouzit lehky fixture/simulator, ale nesmi se prezentovat jako
  finalni dukaz obchodovatelnosti.
- NautilusTrader vyhodnotit az pres ADR, pokud dve nebo vice strategy families potrebuji
  sdilene live/backtest semantics.
- Pro produkci drzet jeden canonical event model; vectorized research je jen filtr, ne dukaz.

### 5.4 Cost and execution layer

Ucel: zrusit iluzi, ze signalovy backtest je obchodovatelny.

Povinne modely:

- explicit fees: maker/taker, tier, category, settlement, funding, borrow, gas,
- spread crossing: bid/ask, not mid,
- slippage: podle hloubky knihy, volatility, participation, order type,
- market impact: minimalne conservative bps model, pozdeji Almgren-Chriss/TCA kalibrace,
- latency: signal-to-order delay, cancel delay, websocket gap,
- fill probability: queue position, maker adverse selection, partial fills,
- order rejection and outage model.

Report musi oddelit:

- gross alpha,
- spread cost,
- explicit fees,
- funding/borrow,
- slippage,
- impact,
- missed fills,
- opportunity cost,
- net alpha.

### 5.5 Validation and robustness layer

Ucel: aktivne chytat overfitting a data snooping.

Povinne metody podle typu strategie:

- Casovy holdout: posledni usek historie zamceny az do finalniho candidate review.
- Walk-forward: pokud strategie potrebuje prubeznou rekalkibraci.
- Purged/embargoed CV: pokud labely nebo holding periods prekryvaji casove intervaly.
- CPCV/CSCV: pro vetsi param-space a ML modely, kde chceme odhadnout PBO.
- Deflated Sharpe Ratio / Probabilistic Sharpe Ratio: pro korekci selection bias a
  nenormalnich returns.
- Reality Check / SPA: pri porovnavani mnoha pravidel nebo variant.
- Regime split: volatility, trend/range, liquidity, funding sign, macro session, exchange
  stress.
- Sensitivity test: male zmeny parametru nesmi dramaticky menit verdikt.
- Stress: fees +50%, slippage +100%, latency +2x, fill rate -30%, forced deleverage,
  exchange outage, correlated gap.

Kill kriterium:

- Strategie konci, pokud edge zmizi po realistickych nakladech.
- Strategie konci, pokud zije jen na jednom uzkem parametru.
- Strategie konci, pokud out-of-sample degradace nema rozumne vysvetleni.
- Strategie konci, pokud live/paper odchylka od backtestu prekroci predem dany limit.

### 5.6 Risk engine

Ucel: zabranit tomu, aby dobra strategie znicila ucet.

Povinne prvky:

- position sizing nezavisly na signal modelu,
- portfolio exposure cap podle assetu, venue, collateral, direction, leverage,
- volatility targeting nebo fixed-fraction sizing,
- fractional Kelly pouze jako horni analyticky odhad, nikdy jako default sizing,
- max daily loss, max weekly loss, max peak-to-trough drawdown,
- consecutive-loss kill switch,
- liquidity cap: max % book depth, max % daily volume/open interest,
- exchange/venue cap,
- model confidence cap,
- manual intervention and freeze mode,
- immutable order and decision journal.

Risk report:

- expected return distribution,
- drawdown distribution,
- risk of ruin proxy,
- tail loss / expected shortfall,
- exposure correlation,
- worst historical windows,
- scenario losses,
- capacity estimate.

### 5.7 Automation layer

Ucel: strategie prevadet na opakovatelne workflow bez chaosu.

Typy automatizaci:

- data health monitor,
- research corpus updater,
- nightly backtest runner,
- candidate gate checker,
- paper trading observer,
- execution drift monitor,
- risk limit monitor,
- post-trade TCA report,
- incident summarizer,
- weekly research review.

Kazda automatizace ma:

- owner,
- schedule nebo trigger,
- vstupy a vystupy,
- allowed actions,
- forbidden actions,
- alert channel,
- rollback/freeze postup,
- run receipt.

### 5.8 UI and reports

Ucel: rychle poznat, co je skutecne pouzitelne.

Views:

- Research backlog: hypotezy, status, owner, expected edge, kill criterion.
- Strategy card: spec, data, metriky, gates, posledni verdikt.
- Experiment explorer: vsechny runy, ne jen viteze.
- Robustness heatmap: parametry, regimes, OOS windows.
- Cost waterfall: gross to net.
- Risk dashboard: exposure, drawdown, stops, kill switches.
- Paper/live divergence: expected vs actual fills, costs, latency, PnL.
- Receipts ledger: kdo/co/kdy/proc zmenil nebo schvalil.

## 6. Agenticky operating model

Navrhovane role:

- `Head Researcher`: pise research brief, schvaluje StrategySpec, rozhoduje gate.
- `Study Scout`: hleda studie, uklada bibliografii, extrahuje tvrzeni a slabiny.
- `Data Steward`: overuje data manifesty, timestampy, missing data, drift.
- `Strategy Implementer`: implementuje signal/backtest podle specu.
- `Execution Skeptic`: hleda nerealisticke fills, fees, slippage, impact, latency.
- `Stats Auditor`: kontroluje PBO, DSR, multiple testing, leakage, OOS split.
- `Risk Officer`: kontroluje sizing, exposure, drawdown, kill switches.
- `Automation Engineer`: bali schvaleny workflow do opakovatelne automatizace.

Navrhovane prikazy:

- `/the-pass:mise`: setup pravidel, slozek, sablon, credentials check bez obchodovani.
- `/the-pass:research <topic>`: najdi zdroje, udelej source map, navrhni hypotezy.
- `/the-pass:spec <idea>`: prepis napad do `StrategySpec`.
- `/the-pass:screen <spec>`: rychly vectorized screen s konzervativnimi naklady.
- `/the-pass:backtest <spec>`: event-driven backtest s artefakty.
- `/the-pass:taste <run>`: nezavisly review dat, statistik, execution a rizika.
- `/the-pass:refire <findings>`: oprav potvrzene problemy bez rozsireni scope.
- `/the-pass:simmer <gate>`: iteruj jen do splneni konkretni brany nebo kill limitu.
- `/the-pass:paper <candidate>`: paper trading se stejnym rozhodovacim kodem.
- `/the-pass:plate <candidate>`: priprava approval packu pro dalsi gate, bez automatickeho live.
- `/the-pass:receipts`: ledger runu, nakladu, zaveru a otevrenych rizik.

Dulezite: `plate` nevytvari live obchodovani. Jen vyrobi balicek pro cloveka.

## 7. Research corpus

Tento corpus neni konecny. Je to prvni povinna knihovna pro design systemu. Kazdy zdroj ma
byt precten s vystupem: `claim`, `evidence`, `limitation`, `system implication`,
`tests we must implement`.

### 7.1 Backtest overfitting and data snooping

- Bailey, Borwein, Lopez de Prado, Zhu: "The Probability of Backtest Overfitting".
  Implication: implementovat CSCV/CPCV a PBO report; nesbirat jen nejlepsi variantu.
- Bailey, Lopez de Prado: "The Deflated Sharpe Ratio".
  Implication: Sharpe reportovat s korekci na multiple testing a nenormalni returns.
- White: "A Reality Check for Data Snooping".
  Implication: pri mnoha pravidlech testovat, zda vitez neni nahoda.
- Hansen: "A Test for Superior Predictive Ability".
  Implication: SPA jako silnejsi varianta pri porovnavani modelu.
- Harvey, Liu, Zhu: "... and the Cross-Section of Expected Returns".
  Implication: t-stat 2 neni dost pro strategy zoo; vsechny experimenty se pocitaji.

### 7.2 Financial ML validation

- Lopez de Prado: "Advances in Financial Machine Learning".
  Implication: purging, embargo, event-based sampling, triple barrier, feature importance,
  meta-labeling pouzit jen pokud resi konkretni problem, ne jako cargo cult.
- Recent CPCV/backtest-overfitting comparisons.
  Implication: walk-forward neni automaticky nejbezpecnejsi; validace musi odpovidat
  label horizonu a strategii.

### 7.3 Market microstructure and execution

- Perold: "The Implementation Shortfall: Paper versus Reality".
  Implication: rozhodovaci cena a skutecna fill cena musi byt oddelene; merime i
  opportunity cost.
- Almgren, Chriss: "Optimal Execution of Portfolio Transactions".
  Implication: impact a volatility risk nejsou detaily; capacity a execution schedule patri
  do backtestu.
- Laruelle, Lehalle: "Market Microstructure in Practice".
  Implication: order book, tick size, fragmentation, auctions, adverse selection a venue
  rules jsou soucast strategie.

### 7.4 Futures, trend following, carry

- Moskowitz, Ooi, Pedersen: "Time Series Momentum".
  Implication: futures trend following je legitimni baseline, ale musi se testovat napric
  asset classes a rezimy.
- Hurst, Ooi, Pedersen: "A Century of Evidence on Trend-Following Investing".
  Implication: dlouha historie trendu je benchmark pro robustnost, ne zaruka.
- Turtle trading rules and Market Wizards corpus.
  Implication: pravidla vstupu jsou mene dulezita nez sizing, exits, disciplina a drawdown
  tolerance.

### 7.5 Crypto and perpetual futures

- Cryptocurrency trading systematic reviews.
  Implication: crypto research je fragmentovany a rychle starnouci; musime mit recency
  tagy a out-of-sample po publikaci.
- Cryptocurrency market microstructure reviews.
  Implication: venue fragmentation, fake liquidity, outages a latency jsou prvotridni rizika.
- Perpetual futures pricing and funding-rate research.
  Implication: funding neni bonus; je to jadro PnL, rizika a crowding/carry decay.
- Intraday crypto predictability studies.
  Implication: intraday momentum/reversal testovat zvlast podle volatility, jumps, sessions a
  liquidity.

### 7.6 Successful investor/operator principles

- Buffett/Berkshire letters.
  Implication: margin of safety, kapitalova disciplina, jednoduchost a nepovinne obchody.
- Dalio/Bridgewater All Weather and Principles.
  Implication: diverzifikace podle zdroju rizika, evidence-based rozhodovani, red-team kultura.
- Druckenmiller interviews.
  Implication: thesis horizon muze byt dlouhy, ale exit musi byt rychly, kdyz data odporuji
  tezi.
- Schwager Market Wizards.
  Implication: neni jeden univerzalni recept; robustni proces a kontrola ztrat jsou castejsi
  nez konkretni indikator.

### 7.7 Public strategy-review corpus

- Oxford Capital Strategies / OxfordStrat Resources.
  Implication: brat jako "strategy zoo" pro generovani baseline hypotez a negativnich
  kontrol, ne jako dukaz edge. Katalog obsahuje verejne review desitek technickych pravidel:
  Donchian/price breakouts, opening range breakout, narrow-range/NR7, false breakout,
  Turtle Soup, Livermore, Wyckoff, Bollinger/Keltner, MACD/RSI/ADX/Aroon/Vortex, volume
  filters, volatility squeeze, volatility clustering a global market correlations. System musi
  umet tyto jednoduche pravidlove strategie reprodukovat, zapocitat naklady a ukazat, ktere
  umiraji po fees/slippage nebo pri OOS validaci.

## 8. StrategySpec draft

Prvni verze formatu:

```yaml
id: crypto_perp_intraday_momentum_v001
title: Intraday crypto perp momentum after liquidity reset
owner: research
status: draft

hypothesis:
  statement: >
    After large liquidity-taking moves, short-horizon continuation exists when order-book
    recovery is weak and funding/open-interest context confirms directional pressure.
  economic_reason: >
    Leverage demand, forced liquidation cascades, inventory constraints, and delayed
    liquidity replenishment can create continuation before mean reversion dominates.
  falsifiable_prediction: >
    Net returns after fees and slippage are positive in OOS windows and degrade smoothly
    under conservative latency/fill assumptions.

market:
  asset_class: crypto_perp
  venues: [binance, bybit]
  instruments: [BTCUSDT-PERP, ETHUSDT-PERP]
  horizon: 5m-2h
  trading_hours: 24/7

data:
  required:
    - trades
    - top_of_book
    - depth_l2
    - funding_rates
    - mark_price
    - index_price
    - open_interest
    - liquidations_if_available
  min_history: 24 months
  timestamp_policy: event_time_receive_time_decision_time

signal:
  features:
    - return_1m_5m_15m
    - book_imbalance
    - spread
    - depth_recovery
    - realized_volatility
    - funding_rate
    - open_interest_change
  model_family: baseline_rules_then_gradient_boosting_if_needed
  forbidden:
    - future bars
    - revised data unavailable at decision time

execution:
  order_types: [post_only_limit, taker_limit]
  max_position_usd: 10000
  max_participation_of_depth: 0.05
  latency_ms_assumption: 250
  cancel_after_ms: 1500

costs:
  fees: venue_tier_specific
  slippage: depth_based
  funding: actual_interval_accrual
  impact: conservative_bps_plus_depth

validation:
  primary: walk_forward_with_embargo
  secondary: cpcv_if_ml
  holdout: latest_20_percent_locked
  stress:
    fees_multiplier: 1.5
    slippage_multiplier: 2.0
    latency_multiplier: 2.0
    fill_rate_multiplier: 0.7

risk:
  sizing: volatility_targeted_fractional
  max_daily_loss_pct: 1.0
  max_strategy_drawdown_pct: 8.0
  max_leverage: 1.0
  kill_switches:
    - paper_backtest_divergence
    - exchange_outage
    - loss_limit
    - fill_quality_breakdown

promotion_gates:
  research_gate:
    min_oos_net_sharpe: 1.0
    max_pbo: 0.10
    dsr_positive: true
  paper_gate:
    min_days: 30
    min_trades: 100
    max_realized_vs_expected_cost_error_pct: 25
  live_gate:
    requires_human_approval: true
```

## 9. Gate-based roadmap

Status note: the phase numbers in `docs/implementation/BUILD_PLAN.md` describe the public
framework build and are implemented. The separate trading research implementation is
controlled by `docs/implementation/TRADING_ROADMAP_EXECUTION_PLAN.md` and its
machine-readable `roadmap-status.yaml`; no roadmap phase is complete without gate evidence.

### Phase 0: Public plugin and research operating system

Build:

- `.codex-plugin/plugin.json`,
- plugin skills for `mise`, `research`, `spec`, `screen`, `backtest`, `taste`, `refire`,
  `simmer`, `paper`, `plate` and `receipts`,
- `research/sources.yaml`: curated bibliography with status.
- `templates/strategy_spec.yaml`.
- `templates/research_brief.md`.
- `templates/audit_report.md`.
- `templates/run_receipt.json`.
- decision ledger.

Gate:

- Plugin manifest validates.
- Public-release checklist passes.
- 20 core sources reviewed into structured notes.
- At least 5 strategy ideas converted to falsifiable `StrategySpec`.
- No code for live trading.

Kill:

- If sources cannot be tied to testable system requirements, stop and rewrite research
  method.

### Phase 1: Adapter and manifest foundation

Build:

- asset-class adapter contract,
- instrument registry schema,
- raw immutable data store policy,
- normalized event schema,
- dataset manifest generator,
- data quality report,
- deterministic feature pipeline.

Gate:

- At least one adapter can ingest or validate a public-safe sample.
- At least one independent cross-check path is documented for that adapter.
- Dataset manifest catches missing intervals, duplicates, timestamp disorder and outliers.
- Same raw data produces identical features twice.

Kill:

- If timestamps or source semantics are unreliable, no strategy work on that source.

### Phase 2: Baseline backtest harness

Build:

- vectorized screen runner,
- event-driven backtest runner,
- cost model v0,
- metrics pack,
- experiment ledger,
- HTML/Markdown report.

Gate:

- Buy-and-hold, random, trend baseline and mean-reversion baseline all run.
- Random strategy is not profitable after costs except by expected noise.
- Cost waterfall is visible for every strategy.

Kill:

- If backtest cannot reproduce known baseline behavior, stop strategy research.

### Phase 3: Robustness and audit

Build:

- walk-forward splitter,
- purged/embargoed splitter,
- PBO/CSCV/CPCV tooling,
- DSR/PSR tooling,
- Reality Check/SPA harness where practical,
- independent audit workflow.

Gate:

- Every promoted candidate includes OOS, PBO/DSR or justified alternative, stress and
  sensitivity.
- Auditor can reproduce run from receipt.

Kill:

- If the framework only saves winning runs, stop and fix experiment ledger.

### Phase 4: Paper trading

Build:

- live data observer,
- paper broker,
- order/fill simulator calibrated from live book,
- decision journal,
- paper-vs-backtest divergence report,
- risk limit monitor.

Gate:

- 30+ days or enough event count for the strategy horizon.
- Realized costs within acceptable error bounds.
- No risk-limit or data-health incident unresolved.
- Strategy still passes original `StrategySpec`, not rewritten after seeing paper results.

Kill:

- If paper fills differ materially from assumptions, strategy returns to execution research.

### Phase 5: Live approval pack

Build:

- human-readable approval document,
- exact config diff from paper to live,
- max capital and max loss limits,
- rollback plan,
- monitoring plan,
- legal/regulatory checklist where relevant.

Gate:

- Explicit human approval.
- Dry-run confirms no credential/order path surprises.
- Live launch starts as micro-live with hard caps.

Kill:

- Any ambiguity about collateral, margin, fee, venue permissions, or real order path.

### Phase 6: Micro-live and scale

Build:

- micro-live with strict caps,
- TCA report,
- adverse selection report,
- risk review after fixed trade count,
- scale proposal only after evidence.

Gate:

- Live realized PnL/cost/fill profile matches paper within tolerance.
- No hidden manual intervention.
- Capacity estimate supports requested size.

Kill:

- Any breach of loss, divergence, data health, or operational safety limits.

## 10. Metrics standard

Every report must include:

- total return, annualized return if meaningful,
- volatility and downside volatility,
- Sharpe, Sortino, Calmar,
- max drawdown, average drawdown, drawdown duration,
- hit rate, payoff ratio, expectancy,
- turnover, average holding period,
- gross vs net PnL,
- fees, spread, slippage, funding, impact,
- tail metrics: VaR/expected shortfall or bootstrap loss percentile,
- exposure by asset/venue/direction,
- capacity estimate,
- PBO/DSR/PSR where applicable,
- OOS vs IS degradation,
- paper/live divergence once available.

Metrics that are dangerous alone:

- Sharpe without costs.
- CAGR without drawdown.
- Win rate without payoff ratio.
- Backtest equity curve without parameter count.
- Paper PnL without fill quality.
- Net PnL without capacity.

## 11. Experiment ledger

Kazdy experiment se zapisuje bez ohledu na vysledek.

Minimalni fields:

```json
{
  "run_id": "2026-07-09T120000Z_crypto_momo_001",
  "strategy_spec_id": "crypto_perp_intraday_momentum_v001",
  "code_ref": "git_sha_or_patch_hash",
  "data_manifest_ref": "sha256",
  "parameters": {},
  "parameter_space_size": 0,
  "cost_model_ref": "cost_v001",
  "validation_method": "walk_forward_embargo",
  "metrics_ref": "report.json",
  "artifacts": ["report.md", "equity.png", "trades.parquet"],
  "verdict": "kill|revise|paper_candidate|blocked",
  "confirmed_findings": [],
  "reviewer": "stats_auditor",
  "created_at": "2026-07-09T12:00:00Z"
}
```

Bez ledgeru neni mozne spolehlive pocitat selection bias.

## 12. Prvni strategicke baseline rodiny

Nez budeme hledat exotiku, postavime benchmarky:

- Time-series momentum pro futures/crypto.
- Cross-sectional momentum/reversal pro crypto universe.
- Carry/basis/funding pro perpetual futures.
- Intraday reversal po liquidity shocku.
- OxfordStrat-style public-domain technical strategy zoo: Donchian, ORB, NR7, Turtle Soup,
  Wyckoff, Livermore, Bollinger/Keltner, RSI/MACD/ADX/Aroon/Vortex.
- Breakout/trend following ala Turtle jako jednoducha disciplinovana baseline.
- Mean reversion s volatility/liquidity filtrem.
- Market-making simulator jen paper/replay, nikdy bez queue/fill/adverse-selection modelu.
- Prediction-market fair-value scanner jako samostatna rodina s vlastnimi fee/settlement
  pravidly.

Cil baseline neni rychle vydelat. Cil je vedet, zda nas system umi rozlisit:

- signal od sumu,
- gross edge od net edge,
- backtest od obchodovatelnosti,
- robustni strategii od prefitovaneho artefaktu.

## 13. Studie-to-system mapping

| Zdroj | Co si bereme | Konkretni systemovy pozadavek |
| --- | --- | --- |
| sous-chef | nezavisly orchestrator, worker, receipts | agenticky workflow s audit ledgerem |
| Bailey et al. PBO | overfitting je meritelny | PBO/CSCV/CPCV report pro param sweeps |
| Deflated Sharpe Ratio | Sharpe je nafouknuty selection biasem | DSR/PSR v metrikach |
| White Reality Check | vitez mnoha testu muze byt nahoda | multiple-strategy correction |
| Hansen SPA | lepsi test superiorni predikce | model comparison gate |
| Harvey/Liu/Zhu | factor zoo vyzaduje vyssi latku | evidence ledger vsech pokusu |
| Lopez de Prado | financni CV musi resit leakage | purging, embargo, event labels |
| Perold | paper portfolio neni realita | implementation shortfall/TCA |
| Almgren-Chriss | impact a risk exekuce | capacity and impact model |
| Market Microstructure in Practice | venue pravidla meni edge | order-book/venue-aware simulator |
| Time Series Momentum | robustni futures baseline | benchmark pred exotickymi napady |
| Crypto reviews | crypto edge rychle starne | recency/OOS-after-publication gate |
| Investor interviews | preziti pred egem | kill switches, sizing, review kultura |

## 14. Team workflow

Tydnove cadence:

- Pondeli: review novych zdroju a hypotez.
- Utery: data quality a baseline runy.
- Streda: implementace kandidatu.
- Ctvrtek: audit, robustness, kill/revise/paper decisions.
- Patek: paper/live divergence, risk review, roadmap.

Definition of done for research note:

- zdroj ma bibliografii a URL/DOI,
- hlavni claim je parafrazovany,
- omezeni studie jsou popsana,
- je jasne, jaky test z toho plyne,
- pokud nejde odvodit test, zdroj je "background", ne evidence.

Definition of done for strategy candidate:

- `StrategySpec` complete,
- data manifest complete,
- backtest reproducible,
- costs realistic,
- OOS and robustness complete,
- audit findings resolved or accepted with rationale,
- promotion/kill verdict recorded.

## 15. Security, credentials, compliance

- Credentials nikdy nepatri do research runu.
- Default mode je read-only/paper.
- Live broker/exchange adapters jsou oddelene od research package.
- Production secrets jsou dostupne jen live runneru, ne agentum pro generovani kodu.
- Kazdy live-capable command vyzaduje explicitni approval flag a lidsky review.
- Logs nesmi leakovat private keys, API secrets ani personal data.
- U regulovanych futures je nutne overit exchange, broker a jurisdiction pravidla pred live.

## 16. Proc nepostavit vse hned

Nejvetsi riziko neni, ze system bude malo chytry. Nejvetsi riziko je, ze bude prilis rychle
generovat presvedcive, ale falesne vysledky. Proto build order musi zustat:

1. research method,
2. data truth,
3. backtest realism,
4. robustness,
5. paper,
6. risk,
7. micro-live.

Pokud tento poradek porusime, agenti jen zrychli p-hacking.

## 17. Prvni 30 dni

Tyden 1:

- Dokoncit plugin scaffold a public-ready repo metadata.
- Zalozit `research/sources.yaml`, sablony a StrategySpec.
- Zpracovat prvnich 20 zdroju do strukturovanych notes.
- Sepsat adapter contract tak, aby fungoval pro crypto, futures, prediction markets a dalsi
  asset classes.

Tyden 2:

- Navrhnout canonical event schema.
- Postavit data manifest generator.
- Nacist nebo namodelovat public-safe sample pro prvni adapter.
- Sepsat provider ADR pro kazdy adapter, ktery ma jit za diagnostic mode.
- Vytvorit data quality report.

Tyden 3:

- Postavit minimalni vectorized screen.
- Postavit minimalni event-driven simulator pro market/limit fill s costs v0.
- Spustit baseline runy a ulozit vsechny experimenty do ledgeru.

Tyden 4:

- Pridat walk-forward, embargo, stress a cost waterfall.
- Implementovat prvni audit report.
- Vydat verdict, ktere baseline jdou do dalsi faze a ktere se zabiji.

Vystup po 30 dnech:

- Ne "profitabilni bot", ale research machine, ktera umi zabit spatne strategie s dukazy.

## 18. Prvni 90 dni

Do 90 dnu by system mel mit:

- 50+ zdroju ve structured corpus,
- 10+ formalnich StrategySpec,
- 3-5 baseline families,
- funkcni public plugin workflow,
- validatory pro artifact kontrakty,
- canonical data/event schema,
- reproducible experiment ledger,
- cost waterfall,
- walk-forward/purged validation,
- PBO/DSR tooling aspon pro relevantni use-cases,
- adapter/provider ADR pro kazdou asset class, ktera jde za diagnostic mode,
- paper trading pro 1-2 nejsilnejsi kandidaty,
- risk dashboard pro paper,
- zadny live trading bez zvlastniho schvaleni.

## 19. Vyreseni 10 otevrenych temat

Tato sekce prevadi otevrene otazky na konkretni defaulty. Kazde rozhodnuti muze byt
zmeneno pouze pres ADR, novou evidenci a reprodukovatelny experiment. Dokud neni ADR
zmeneno, plati zde uvedeny default.

### 19.1 Decision log / ADR

Rozhodnuti: zalozit formalni ADR proces hned ve Phase 0. Bez ADR se nesmi menit engine,
storage, data provider, promotion gates, live-capable boundary ani risk governance.

Adresare a soubory:

- `docs/adr/ADR-0001-product-scope.md`
- `docs/adr/ADR-0002-storage.md`
- `docs/adr/ADR-0003-engine.md`
- `docs/adr/ADR-0004-data-providers.md`
- `docs/adr/ADR-0005-risk-governance.md`
- `docs/adr/ADR-0006-plugin-and-public-distribution.md`
- `docs/adr/ADR-0007-artifact-schemas.md`

ADR sablona:

```markdown
# ADR-0000: Title

Status: proposed|accepted|superseded
Date: YYYY-MM-DD
Owner: head_researcher|risk_officer|data_steward

## Context

What problem exists, what constraints matter, and what evidence is available.

## Decision

One concrete decision. No vague "consider" language.

## Alternatives Considered

- Alternative A: why rejected
- Alternative B: why rejected

## Consequences

- Positive consequences
- Negative consequences
- New risks

## Validation

Commands, reports, experiments, or external docs that prove the decision is still sane.

## Review Trigger

When this ADR must be revisited.
```

Acceptance criteria:

- Every accepted ADR references at least one source, experiment, or repo artifact.
- Every superseded ADR links to its replacement.
- No strategy candidate can pass `research_gate` if its engine, data source, or cost model is
  not covered by an accepted ADR.

### 19.2 MVP scope

Rozhodnuti: MVP je The Pass v0, public plugin-first review station, ne trading bot a ne
jedna konkretni strategie. Cilem je dodat workflow, artefaktove kontrakty, gate model a
bezpecnostni hranice, ktere se daji pouzit pro crypto, futures, prediction markets,
equities, FX, options i dalsi asset classes.

Core MVP:

- Plugin manifest and skills.
- ADR process and public repo policy.
- `StrategySpec`, source note, data manifest, run receipt, metrics report, cost waterfall
  and verdict report contracts.
- Asset-class adapter contract.
- Gate workflow: research -> screen -> backtest -> taste -> refire/simmer -> paper -> plate.
- Safety boundary: no secrets, no real order path, no live-capable code without separate ADR.

Adapter examples, not product scope:

- Crypto perps: Binance/Bybit public scaffolding, Tardis.dev/Kaiko for audited replay.
- Listed futures: Databento or licensed equivalent plus roll/calendar policy.
- Prediction markets: Polymarket/Kalshi market data plus settlement semantics and fee/depth
  checks.
- Equities/options/FX/rates/credit: provider and market-structure ADR before promotion.

Explicitly out of MVP:

- Live trading.
- Real order placement.
- Broker/exchange credentials.
- Private data or paid data redistribution.
- A hard dependency on one backtesting engine.
- Treating public examples as proof of edge.

MVP is complete only when:

- Plugin skills exist and map to the planned workflow.
- Core templates have machine-validatable schemas or schema-ready examples.
- At least one public-safe example can move from research note to verdict without live access.
- Every run creates a data manifest, run receipt, metrics report, cost waterfall and verdict.
- At least one intentionally bad/random baseline is killed by the framework.
- Public-release checklist passes.

### 19.3 Data provider matrix

Rozhodnuti: startovat free/public data only for scaffolding, but do not trust free/public
data for final strategy verdicts that depend on queue, depth, funding, open interest or
intraday fills. Any candidate that survives screening must be retested on a paid or
independently archived source before paper promotion.

| Market | Default provider | Backup / paid provider | Required fields | Use | Blocker |
| --- | --- | --- | --- | --- | --- |
| Crypto spot | Binance public WS/REST | Kaiko, Tardis.dev | trades, klines, top book/depth | reference prices, volatility, spot leg | no timestamp/sequence audit |
| Crypto perps | Binance USD-M public REST/WS | Bybit public, Tardis.dev, Kaiko | trades, depth, mark, index, funding, open interest, liquidations if available | adapter example | missing funding/OI for held positions |
| Crypto cross-venue | Binance + Bybit | Tardis.dev normalized replay | venue-specific trades/depth/funding | venue robustness, not arbitrage | symbol/contract mismatch |
| Futures | none free for final verdict | Databento | trades, MBP-1/10, MBO where needed, OHLCV, instrument metadata | adapter example | licensing, roll policy, fees |
| Prediction markets | Polymarket Gamma/Data/CLOB public | archived raw store, Allium/other warehouse if licensed | market metadata, books, trades, settlement, fees | later adapter | resolution semantics not verified |
| Regulated event markets | Kalshi public market data | vendor/warehouse for history | events, markets, orderbook, settlement | reference/overlap research | API/license constraints |
| Macro/session calendar | exchange calendars | paid calendar vendor | holidays, sessions, contract expiry | futures validation | incorrect session/roll calendar |

Provider acceptance checklist:

- Raw response can be stored immutably.
- Terms/licensing allow backtesting and internal research.
- Event time and receive time can be separated.
- Symbol/instrument metadata includes tick size, lot size, contract multiplier and quote
  currency.
- Historical data can be replayed deterministically.
- Provider outage or truncation is detectable.
- Data can be cross-checked against another source for a sample window.

Initial decision:

- Core does not choose a single default provider.
- Adapter examples may use public/free data for scaffolding.
- Any adapter that wants paper promotion must pass provider acceptance and licensing review.
- Do not buy broad institutional data until an adapter has a concrete validation need.

### 19.4 Build vs buy

Rozhodnuti: build the research operating system, buy/reuse engines only where they reduce
risk. The core asset is not a backtester package; it is the evidence ledger, data manifest,
cost model, audit workflow and promotion gates.

Default stack:

- Storage: Parquet files partitioned by `source/venue/instrument/date` for raw and normalized
  market data where adapters need data files; DuckDB for local analytical queries; the MVP
  receipt ledger is append-only JSONL with a SHA-256 hash chain; SQLite is deferred until
  scale requires it, and Postgres remains reserved for concurrent multi-user operation.
- Screening: adapter-selected engine. pandas/NumPy and vectorbt are allowed examples, never
  final execution proof by themselves.
- Event simulation: adapter-selected engine. Any simulator must expose explicit cost, fill,
  timestamp and safety assumptions.
- Production-grade engine: evaluate NautilusTrader, LEAN, Backtrader or custom engines via
  adapter ADRs, not as core identity.
- QuantConnect/LEAN: useful architectural reference for Universe -> Alpha -> Portfolio ->
  Risk -> Execution separation, but not required core runtime.
- Backtrader: acceptable only where the adapter documents why bar-level assumptions are
  sufficient.

Build in-house:

- `StrategySpec`
- data manifest and dataset fingerprint
- experiment ledger
- cost waterfall
- promotion gates
- source review notes
- paper/live divergence reports
- safety and credential boundaries

Reuse/buy:

- exchange data APIs,
- paid historical replay data when needed,
- vectorized research helpers,
- plotting/report libraries,
- eventual event engine if it preserves our event model and audit requirements.

ADR trigger to move to NautilusTrader:

- At least two strategy families require shared live/backtest semantics.
- In-house simulator has duplicated order lifecycle or portfolio accounting logic.
- Candidate has survived paper and needs micro-live but we still lack robust reconciliation.
- Adapter work is less risky than maintaining a bespoke execution simulator.

### 19.5 Source review protocol

Rozhodnuti: every source becomes a structured note before it can influence a strategy.
Reading many studies is not enough; each must map to a falsifiable test or be marked as
background.

Source note schema:

```yaml
id: bailey-pbo-2014
type: academic|book|interview|vendor-doc|strategy-review|blog|code
priority: P0|P1|P2|P3
status: unread|skimmed|reviewed|implemented|rejected
url: ""
bibliography: ""
claim: ""
evidence: ""
limitations: ""
market_applicability: [crypto_perp, futures, prediction_market]
tradable_implication: ""
required_tests: []
failure_modes: []
system_requirements: []
notes_owner: ""
review_date: YYYY-MM-DD
```

Priority rules:

- P0: affects safety, overfitting, data leakage, execution realism, risk, or live boundary.
- P1: introduces a baseline strategy family or validation method.
- P2: improves reporting, UX, or automation.
- P3: interesting background without direct system requirement.

Review workflow:

- `Study Scout` extracts claim/evidence/limitations.
- `Stats Auditor` maps the source to validation requirements.
- `Execution Skeptic` maps market-structure sources to cost/fill assumptions.
- `Head Researcher` decides whether the source changes StrategySpec templates or gates.

Acceptance criteria:

- No source is cited as evidence until `status=reviewed`.
- No strategy based on a source can pass `research_gate` unless the source note lists
  `required_tests`.
- OxfordStrat and similar strategy-review pages are tagged `strategy-review`, not
  `academic`; they generate baselines and negative controls, not proof of edge.

### 19.6 Strategy taxonomy

Rozhodnuti: classify strategies by edge mechanism, not by indicator name. Every
`StrategySpec` must declare exactly one primary family and optional secondary tags.

| Family | Edge thesis | MVP status | Required data | Special validation | Kill focus |
| --- | --- | --- | --- | --- | --- |
| Time-series momentum | persistence after underreaction | allowed | bars/trades, vol, roll/funding | multi-regime OOS, cross-asset portfolio | one-market-only edge |
| Breakout / ORB / Donchian / NR7 | volatility expansion after compression | allowed | bars, session calendar, spread | parameter stability, false breakout stress | narrow parameter island |
| Mean reversion | liquidity overshoot reverts | allowed with liquidity filter | trades, depth, volatility | regime split by volatility/liquidity | catching falling knives |
| Funding / carry / basis | leverage demand pays shorts/longs | allowed paper-only | funding, mark/index, spot/perp basis, borrow | funding reversal stress, crowding decay | unhedged directional beta |
| Cross-sectional momentum/reversal | relative winners/losers persist/revert | allowed after universe data | multi-asset synchronized bars | survivorship/universe audit | liquidity concentration |
| Statistical arbitrage | relative value mean reverts | deferred | synchronized venues/assets, borrow/funding | cointegration stability, capacity | relationship breakdown |
| Microstructure taker | short-horizon imbalance predicts move | deferred until L2 replay | depth, trades, latency | queue/fill/latency stress | slippage erases edge |
| Market making | spread capture beats adverse selection | deferred; paper/replay only | L2/L3, queue, fills, cancel latency | adverse selection and queue model | toxic flow |
| Prediction-market fair value | external reference differs from book | adapter only | market metadata, books, reference source, settlement | resolution semantics, fee/depth | mapping/resolution mismatch |
| Event/news/NLP | information diffuses slowly | out of MVP | timestamped news/events | publication latency audit | lookahead/news timestamp leakage |
| ML meta-model | combines validated features | out of MVP until baselines work | feature store, labels, train/test manifest | purged/CPCV, DSR/PBO | black-box overfitting |

Rule: if a strategy cannot explain its edge mechanism in one family row, it is not ready for
implementation.

### 19.7 Exact promotion gates by asset class

Rozhodnuti: promotion gates differ by asset class and horizon. A strategy passes the next
gate only if all hard gates pass and no critical audit finding remains unresolved.

Universal hard gates:

- Complete `StrategySpec`.
- Complete data manifest.
- No lookahead/leakage finding.
- Gross and net metrics both reported.
- Cost waterfall present.
- All tried parameter variants recorded.
- Random/null baseline included.
- Human-readable audit report generated.

Crypto intraday/perp gates:

- Minimum history: 12 months for screen, 24 months preferred for promotion.
- Holdout: latest 20% locked before candidate selection.
- Minimum trades: 500 historical trades for intraday candidate or 100 trades for 4h+ horizon.
- OOS net Sharpe: >= 1.0 after fees, spread and slippage.
- DSR/PSR: positive versus zero Sharpe after multiple-test adjustment.
- PBO: <= 0.10 for sweeps with enough combinations; otherwise explicit limitation.
- Stress: survives fees x1.5, slippage x2.0, latency x2.0, fill rate x0.7.
- Drawdown: max historical drawdown <= 2x expected annualized net return or accepted by Risk
  Officer with lower sizing.
- Paper gate: 30 calendar days and either 100 fills or 500 signals, with realized costs within
  25% of model and no unresolved data outage.

Crypto funding/carry gates:

- Minimum history: 18 months or 200 funding intervals across at least two regimes.
- Report directional beta separately from funding PnL.
- Stress: funding flips sign for the worst historical 10% windows; spot/perp hedge slips by
  spread + depth haircut.
- Kill if net PnL is mostly directional beta rather than funding/basis.

Listed futures trend gates:

- Minimum data: 10 years daily or 3 years intraday for each instrument, unless explicitly
  labeled exploratory.
- Portfolio breadth: at least 6 instruments across 3 sectors for production candidate, or
  single-market candidate stays research-only.
- OOS net Sharpe: >= 0.7 portfolio-level after roll, fees and slippage.
- Positive contribution: no single instrument contributes more than 40% of total OOS PnL.
- Roll policy: fixed and documented before test.
- Paper gate: simulated live/paper for at least 60 trading days or 30 trades, whichever is
  later.

Prediction-market gates:

- Mapping gate: market and reference source semantics manually reviewed.
- Fee/depth gate: positive edge survives live fee and executable size depth.
- Paper collection: 1000+ paper-ready signals before any risk review, unless ADR accepts a
  lower threshold for rare events.
- Resolution gate: settlement outcomes reconciled against source-of-truth.
- Kill if edge exists only in gross mid prices.

Live gate for all asset classes:

- Separate human approval required.
- Micro-live cap documented in ADR.
- Credentials and order path verified by dry-run without sending orders.
- Rollback and incident runbook attached.

### 19.8 Execution realism policy

Rozhodnuti: all backtests default pessimistic. Any optimistic fill assumption must be
explicitly labeled and cannot support paper/live promotion.

Default fill rules:

- Market/taker order: fill at visible opposite best price plus fee; if size exceeds visible
  depth, walk the book; if no depth exists, reject the simulated order.
- Limit maker order: no fill unless subsequent trade/book movement proves the price was
  executable; fill is partial by default; assume adverse selection unless queue model proves
  otherwise.
- Mid-price fill: forbidden for promotion; allowed only for diagnostic gross-edge screens.
- Close/open bar fill: allowed only if decision timestamp is before the fill bar and slippage
  is applied.
- Stop/take-profit: trigger on trade-through or conservative high/low logic, never on close
  price alone.

Default cost assumptions:

- Crypto taker: venue-specific taker fee, spread crossing, depth walk, funding accrual for
  held perp positions, conservative slippage floor.
- Crypto maker: venue-specific maker fee/rebate, queue haircut, adverse-selection haircut,
  cancel latency.
- Futures: exchange/broker commission, tick value, spread, roll slippage, exchange session
  gaps.
- Prediction markets: category/market-specific fee endpoint where available, bid/ask depth,
  settlement and failed/partial fill handling.

Stress defaults:

- Fees x1.5.
- Slippage x2.0.
- Latency x2.0.
- Available depth x0.5 in normal stress and x0.25 in severe stress.
- Maker fill probability x0.5 unless calibrated from paper.
- Funding/basis worst-decile stress for carry.

Latency policy:

- Record `event_time`, `receive_time`, `decision_time`, `order_created_time`,
  `order_ack_time`, `fill_time`.
- Adapter default latency must be stated before a run. If not measured, it must be
  pessimistic and marked as a limitation.
- Any strategy requiring less than 100 ms edge is outside core examples and needs a dedicated
  latency/market-structure ADR before research promotion.

### 19.9 Risk governance

Rozhodnuti: risk is independent from strategy research. A strategy cannot grant itself size,
leverage, live access or new venues.

Roles:

- `Head Researcher`: approves research specs and kill/revise/paper-candidate verdicts.
- `Stats Auditor`: can block promotion for overfitting/leakage/multiple-testing issues.
- `Execution Skeptic`: can block promotion for unrealistic fills/costs/latency.
- `Risk Officer`: owns sizing, exposure, drawdown, live boundary and freeze decisions.
- `Operator`: executes approved runbooks; cannot change StrategySpec or risk limits ad hoc.

Default permissions:

- Research agents: read/write research artifacts, no secrets, no order credentials.
- Paper runner: market-data credentials only, virtual broker only.
- Live runner: separate process, separate config, least-privilege exchange credentials, no
  code-generation agent access.
- Human approval required for every live-capable config change.

Default risk caps before first live ADR:

- Research capital: 0.
- Paper capital: virtual only.
- Micro-live cap: min(100 USD notional, 0.25% of approved account equity) per strategy unless
  a later ADR sets lower/higher.
- Max daily live loss during micro-live: min(25 USD, 0.10% account equity).
- Max strategy drawdown before freeze: 3x expected daily volatility or explicit dollar cap,
  whichever is lower.
- Max leverage in MVP: 1.0x effective exposure unless Risk Officer approves lower-risk hedge
  structure.

Promotion governance:

- `research_gate` can recommend paper only.
- `paper_gate` can recommend risk review only.
- `risk_review` can prepare live approval pack only.
- `live_approval` must be explicit, dated and tied to exact config hash.

### 19.10 Incident response

Rozhodnuti: incidents are expected. The system must fail closed, preserve evidence and
separate "pause", "freeze", "kill" and "post-mortem".

Severity levels:

| Severity | Trigger examples | Immediate action | Resume condition |
| --- | --- | --- | --- |
| S0 critical | unexpected live order path, credential leak, live loss cap breach, corrupted ledger | kill live runner, revoke keys if needed, notify human | written post-mortem and new ADR |
| S1 high | feed outage during paper/live, order reject spike, paper/live cost divergence >50%, settlement mismatch | freeze affected strategy and venue | data/risk officer sign-off |
| S2 medium | missing data interval, latency x2 normal, fill rate below stress band, report reproducibility failure | pause promotion, continue data capture if safe | fixed manifest/report rerun |
| S3 low | source note stale, noncritical provider warning, visualization/report defect | log issue | next weekly review |

Standard runbooks:

- Feed outage: mark data source unhealthy, stop new decisions, keep raw reconnect logs, do not
  backfill silently without a manifest note.
- Cost divergence: freeze promotion, compare predicted vs realized spread/slippage/fees,
  update cost model only through ADR.
- Drawdown breach: stop new paper/live entries, allow only risk-reducing exits if live, write
  loss attribution before restart.
- Order rejects: stop order generation, classify reject reason, verify symbol/permissions/size
  and venue status.
- Settlement mismatch: block the market family, reconcile source-of-truth, invalidate affected
  paper signals.
- Data corruption: quarantine dataset partition, recompute fingerprint, rerun affected reports.

Post-mortem template:

```markdown
# Incident YYYY-MM-DD: title

Severity: S0|S1|S2|S3
Affected strategy/venue/data source:
Timeline:
Impact:
Root cause:
What detected it:
What failed to detect it:
Immediate fix:
Permanent fix:
Artifacts invalidated:
ADR required: yes|no
```

## 20. Zdrojovy seznam pro dalsi cteni

- tomascupr/sous-chef README:
  https://github.com/tomascupr/sous-chef
- Bailey, Borwein, Lopez de Prado, Zhu, "The Probability of Backtest Overfitting":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Bailey, Lopez de Prado, "The Deflated Sharpe Ratio / Correcting for Selection Bias":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- White, "A Reality Check for Data Snooping":
  https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152
- Hansen, "A Test for Superior Predictive Ability":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=264569
- Harvey, Liu, Zhu, "... and the Cross-Section of Expected Returns":
  https://www.nber.org/papers/w20592
- Lopez de Prado, "Advances in Financial Machine Learning" lecture material:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3257420
- Perold, "The Implementation Shortfall: Paper versus Reality":
  https://www.hbs.edu/faculty/Pages/item.aspx?num=2083
- Almgren, Chriss, "Optimal Execution of Portfolio Transactions":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=53501
- Laruelle, Lehalle, "Market Microstructure in Practice":
  https://www.worldscientific.com/worldscibooks/10.1142/8967
- Moskowitz, Ooi, Pedersen, "Time Series Momentum":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- Hurst, Ooi, Pedersen, "A Century of Evidence on Trend-Following Investing":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026
- Ackerer, Hugonnier, Jermann, "Perpetual Futures Pricing":
  https://finance.wharton.upenn.edu/~jermann/AHJ-main-10.pdf
- Cryptocurrency trading systematic mapping study:
  https://www.sciencedirect.com/science/article/pii/S2667096824000296
- Cryptocurrency market microstructure systematic review:
  https://link.springer.com/article/10.1007/s10479-023-05627-5
- Intraday return predictability in cryptocurrency markets:
  https://ideas.repec.org/a/eee/ecofin/v62y2022ics1062940822000833.html
- QuantConnect Algorithm Framework overview:
  https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- NautilusTrader documentation:
  https://nautilustrader.io/docs/latest/
- vectorbt documentation:
  https://vectorbt.dev/
- Backtrader documentation:
  https://www.backtrader.com/docu/
- DuckDB Parquet documentation:
  https://duckdb.org/docs/lts/data/parquet/overview.html
- Binance Developer Docs:
  https://developers.binance.com/en/docs
- Bybit API documentation:
  https://bybit-exchange.github.io/docs/v5/market/orderbook
- Databento market data documentation:
  https://databento.com/docs/api-reference-historical
- Tardis.dev documentation:
  https://docs.tardis.dev/
- Kaiko market data overview:
  https://www.kaiko.com/products/l1-l2-data
- Polymarket market data documentation:
  https://docs.polymarket.com/market-data/overview
- Kalshi market data documentation:
  https://docs.kalshi.com/getting_started/quick_start_market_data
- Berkshire Hathaway shareholder letters:
  https://www.berkshirehathaway.com/letters/letters.html
- Bridgewater All Weather:
  https://www.bridgewater.com/research-and-insights/the-all-weather-story
- Ray Dalio Principles:
  https://www.principles.com/
- Morgan Stanley Hard Lessons: Stan Druckenmiller:
  https://www.morganstanley.com/insights/videos/hard-lessons/duquesne-stan-druckenmiller-iliana-bouzali
- Oxford Capital Strategies / OxfordStrat Resources:
  https://oxfordstrat.com/resources/
