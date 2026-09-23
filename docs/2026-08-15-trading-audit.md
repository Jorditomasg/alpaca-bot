# Auditoría de estrategia — 15 ago 2026

Revisión de las tres estrategias (`trailing`, `copy`, `wheel`) usando como
checklist las skills de [claude-trading-skills](https://github.com/tradermonty/claude-trading-skills),
instaladas en `.claude/skills/`.

**Resumen en una línea:** el bot no estaba perdiendo dinero — no estaba
operando. De las tres estrategias, una llevaba días muerta por un bug, otra no
podía abrir una sola posición por una configuración imposible, y la tercera
tenía desplegado el 5 % del capital.

Estado del contenedor al empezar: `Up 5 days`, equity ~$1 095, y de $1 095
solo ~$54 en riesgo.

---

## Hallazgos

### 1 · La estrategia `trailing` moría en el primer stop-out — CORREGIDO

**Evidencia.** `docker logs alpaca-bot` contiene un único ciclo completo:

```
[TRAILING] Resuming AMZN: entry=$246.47 floor=$221.82
[STRATEGY] Floor raised $221.82 → $252.38
...
[STRATEGY] Floor raised $260.10 → $262.73
[TRAILING] SELL | Floor breached — price=$265.03 floor=$265.04
```

Después: nada. No hay `data/trailing_state.json` y no hubo reentrada.

**Causa.** `trailing_task()` era una línea recta: entrar una vez, y bloquearse
para siempre dentro de `trailing_stream.start()`. Al saltar el stop,
`trailing_state.clear()` borraba el fichero de estado, y a partir de ese
momento cada tick entraba en `on_price` y salía inmediatamente por la guarda
`if current is None: return`. El supervisor seguía transmitiendo AMZN — un
símbolo que ya no se tenía — ocupando la **única conexión de datos** que Alpaca
permite por cuenta. Solo un reinicio del contenedor lo revivía, y nadie lo
reinició.

Es exactamente la clase de fallo que el propio `CLAUDE.md` §7 describe para el
kill switch: *una estrategia que se retira sola en silencio.*

**Arreglo.** `trailing/stream.py` gana un `StreamHandle` que apaga el
supervisor, y `trailing_task()` pasa a ser un bucle: posición → stream →
cierre → enfriamiento → siguiente posición.

Detalle no obvio: `on_price` corre **dentro del event loop del propio stream**,
y `StockDataStream.stop()` del SDK hace
`run_coroutine_threadsafe(...).result(timeout=5)`. Llamarlo desde ese loop
bloquea el loop que tiene que atender la corrutina — 5 s de parón garantizados
en cada salida. Por eso el handle expone `astop()`, que usa `stop_ws()`
(encola el mensaje de parada en el loop que ya está corriendo) y solo cae a
`stop()` como último recurso.

Dos decisiones de criterio, ambas configurables:

| Variable | Default | Por qué |
|---|---|---|
| `TRAILING_REENTRY_COOLDOWN_SECONDS` | `3600` | Reentrar en el mismo tick que cerró la posición es recomprar justo lo que acaba de romper el floor. |
| `TRAILING_ENTRY_RETRY_SECONDS` | `300` | Una orden market a las 03:00 ET se encola hasta la apertura y ejecuta a un precio desconocido, ciega al floor con el que se dimensionó. |

Tests: `tests/unit/test_stream.py::TestStreamHandle` (7).

---

### 2 · El `wheel` no podía abrir una posición ni una sola vez — DIAGNOSTICADO

**Evidencia.** `data/wheel_state.json` marca `cycles: 0`, `total_premium: 0.0`
desde que se abrió la cuenta el 1-may-2026. El log es un muro ininterrumpido de:

```
[SPREAD] reject 16.5/14.5@2026-09-04 score=0.08 <0.30
[WHEEL] no decent spread today for SOFI
```

**Causa.** `score = credit / max_loss` cae monótonamente conforme el strike
corto se aleja del dinero: un strike más lejano es menos probable que se rompa,
así que paga menos. Los dos parámetros están acoplados y su configuración
actual es **mutuamente inalcanzable**.

Medido contra la cadena real de SOFI (15-ago-2026, spot $18.29, ancho $2, 20-27 DTE):

| OTM % | strikes | crédito | max loss | score |
|---|---|---|---|---|
| 12.5 % | 16.0 / 14.0 | $6 – $12 | ~$190 | 0.03 – 0.06 |
| **9.8 %** | 16.5 / 14.5 | $15 – $16 | ~$184 | **0.08 – 0.09** ← el target configurado |
| 7.1 % | 17.0 / 15.0 | $15 – $24 | ~$180 | 0.08 – 0.14 |
| 4.3 % | 17.5 / 15.5 | $28 – $32 | ~$170 | 0.17 – 0.19 |
| 1.6 % | 18.0 / 16.0 | $46 – $53 | ~$150 | **0.30 – 0.36** ← el umbral configurado |

Con `WHEEL_TARGET_OTM_PCT=0.10`, el techo real es **0.09**. El umbral es
**0.30**, alcanzable solo vendiendo a ~1.6 % OTM, es decir prácticamente at-the-money.

Y hay un segundo candado encima: `_fetch_option_chain()` recorta los strikes
pedidos a `[target_short - width - 1, target_short + 1]`. El motor **ni
siquiera descarga** los strikes que podrían calificar. Subir solo el umbral no
serviría de nada; la ventana es la restricción vinculante.

**Qué se ha hecho.** No he tocado la calibración: elegir entre más prima y más
riesgo de asignación es una decisión de riesgo tuya, no de código, y `CLAUDE.md`
§1 exige backtest antes de tocar lógica de selección. Lo que sí he hecho es que
la situación **deje de ser invisible**:

- `wheel/spreads.py::best_reachable_score()` mide el techo real de la cadena
  ignorando el umbral, distinguiendo "hoy el mercado paga poco" de "tu umbral
  es inalcanzable" de "no hay cotizaciones a dos caras".
- `wheel/feasibility.py` cuenta ciclos secos y, tras 40 seguidos
  (`WHEEL_INFEASIBLE_AFTER_CYCLES`, ~1,5 sesiones), emite **una sola** alerta
  con el techo medido y el umbral, por log y por Telegram.

Refactor de apoyo: el scoring se extrajo a `spreads.score_candidates()` (puro,
sin umbral) y `best_bull_put_spread()` pasó a ser un filtro sobre él. Los 20+
tests existentes de `test_spreads.py` pasan sin cambios.

Tests: `tests/unit/test_feasibility.py` (10), `test_spreads.py` (+4).

**RESUELTO el 15-ago.** El usuario eligió la opción de más prima. Aplicado en
`.env` (backup en `.env.bak.20260815`):

```
WHEEL_TARGET_OTM_PCT=0.04
WHEEL_SCORE_THRESHOLD=0.15
```

**Es 0.04 y no 0.05, y el motivo importa.** Los strikes de SOFI van de $0.50 en
$0.50, y `best_bull_put_spread` coge *el strike más alto que no supere*
`spot × (1 − target_otm_pct)`. Con 0.05 el target cae en $17.38 y baja un
escalón entero a 17.0/15.0 → score **0.140**, otra vez por debajo del umbral:
habría recreado exactamente el mismo bug. Con 0.04 el target es $17.56 y coge
17.5/15.5 → score **0.194**.

Verificado ejecutando el motor real (`_fetch_option_chain` +
`score_candidates`) contra la cadena en vivo, no derivado a mano:

| OTM config | Elige | OTM real | Score | ¿Pasa 0.15? |
|---|---|---|---|---|
| 0.03 | 17.5/15.5 | 4.3 % | 0.194 | sí |
| **0.04** | **17.5/15.5** | **4.3 %** | **0.194** | **sí** |
| 0.045 | 17.0/15.0 | 7.1 % | 0.140 | no |
| 0.05 | 17.0/15.0 | 7.1 % | 0.140 | no |
| 0.10 | 16.0/14.0 | 12.5 % | 0.064 | no |

**La ventana de strikes NO hizo falta ampliarla.** Era vinculante a 10 % OTM
(`max_strike = target_short + 1` = $17.46, dejando fuera 17.5 y 18.0), pero a
4 % la ventana es `[14.56, 18.56]` y ya contiene los strikes que califican.

Lección de calibración: **el escalón del strike ladder domina sobre el
porcentaje configurado**. Con strikes de $0.50 sobre un subyacente de $18, cada
escalón son ~2.7 puntos porcentuales de OTM — más que la diferencia entre
"conservador" y "agresivo" en el propio parámetro. No calibrar este par sin
simular qué strike se acaba eligiendo.

Los defaults del código se dejan intactos a propósito (`CLAUDE.md` §1 y §3),
con un aviso en `wheel/config.py` para quien despliegue en otro sitio.

---

### 3 · La estrategia `copy` nunca consultaba el kill switch — CORREGIDO

`shared/kill_switch.py` dice literalmente *"Designed to be queried by every
strategy"*. `wheel/engine.py` lo consulta en `IDLE`; la entrada de `trailing`
lo consulta. `copy_trader/` **no lo consultaba en ningún punto** — y era la
única de las tres que tenía posiciones abiertas.

Consecuencia: un drawdown de cuenta del -20 % paraba el wheel (que no operaba
igualmente) y dejaba a copy abriendo nombres nuevos sin ningún freno.

**Arreglo.** `execute_batch(..., halted=)`. Las compras se saltan; las ventas
pasan siempre, igual que `_run_copy_exits`, respetando el sesgo *fail-open*
documentado en §7: un halt debe dejar el riesgo **gestionado**, no congelado.
Una compra bloqueada por halt **no** se marca como vista, así que se reintenta
en cuanto el halt se libere y mientras el filing siga fresco.

Tests: `tests/unit/test_copy_portfolio.py` (+4).

---

## Hallazgos no corregidos (requieren decisión o backtest)

### 4 · El `win_rate` del scorer no discrimina en mercado alcista

`copy_trader/scorer.py::_calculate_win_rate` cuenta qué fracción de las compras
está por encima del precio de entrada **hoy**, sin benchmark. En un mercado que
sube, todo el mundo puntúa cerca de 1.0 y el término deja de separar: el
ranking pasa a decidirse por `recency` y `volume`, o sea que sigue a quien
**más opera**, no a quien mejor acierta.

Dos problemas más en la misma función:
- La muestra es solo lo que hay en las ~3 páginas scrapeadas, no el historial.
- Hace una llamada `get_stock_bars` **por cada compra** — N round-trips por
  scoring.

El arreglo correcto es hacerlo relativo al benchmark (exceso sobre SPY en la
misma ventana). Es lógica de entrada → pasa por el gate de backtest de §1.
Anotado como CAVEAT en el docstring del módulo.

### 5 · Utilización de capital: 5 % desplegado

Con equity de $1 095 y `MAX_POSITIONS=8` / `NOTIONAL_PCT=5 %`, el libro objetivo
son 8 × $54.75 ≈ $438 (40 %). Real: **2 posiciones de $27.03** (PG y V, ambas
del 13-may-2026, dimensionadas bajo el código viejo de rebalanceo). El embudo
es seguir a **un solo político**: con 29 trades por poll repartidos entre todos,
al seguido le tocan muy pocos, y encima tienen que superar `MIN_AMOUNT=$15 000`
y 30 días de frescura.

`MIN_AMOUNT=15000` se validó sobre un backtest de $100 000. En una cuenta de
$1 000 sigue teniendo sentido como filtro de *convicción*, pero conviene
comprobar que no está estrangulando el flujo hasta dejarlo en nada.

### 6 · Los tres colchones de capital compiten sin árbitro

`CLAUDE.md` §5 avisa de esto pero nada en el código lo hace cumplir. Con equity
$1 095: copy puede desplegar hasta el 80 % ($876), trailing coge el 30 % del
buying power en la entrada, y el wheel necesita `min_buying_power=$400` o se
para en seco. Los tres a la vez no caben. Hoy no se nota porque dos de las tres
no operaban; en cuanto operen las tres, el wheel será el que se quede fuera —
silenciosamente, por su `_capital_guard`.

### 7 · Menores

- **`datetime.utcnow()`** — 6 usos. Además de estar deprecado en Python 3.12
  (la imagen corre 3.12; el venv local es 3.11), es semánticamente flojo: el
  `today_iso` que alimenta `MAX_HOLDING_DAYS` se calcula en UTC, así que a
  partir de las 20:00 ET ya es "mañana" y la salida por vencimiento de señal
  puede dispararse un día antes.
- **`market_hours.is_market_open()` ignora los festivos** — solo mira fin de
  semana y horario. En un festivo el wheel corre ciclos y las órdenes se
  encolan. Alpaca expone un endpoint de calendario.
- **`seen_trade_ids` crece sin límite** — 605 entradas hoy, y la pertenencia se
  comprueba con `in` sobre una lista (O(n) por trade). No es urgente, pero no
  hay poda.
- **`get_consensus_ticker` cae a `"TSLA"` hardcoded** si el scraper falla. La
  entrada de trailing es el 30 % del buying power: un fallo del scraper compra
  TSLA sin que nadie lo haya decidido.
- **Ninguna estrategia mira el régimen de mercado.** No hay filtro de tendencia
  ni de breadth en ningún punto de entrada. Es precisamente el hueco que cubren
  las skills `market-breadth-analyzer` y `uptrend-analyzer`, que no necesitan
  API key (leen CSV público).

---

## Skills instaladas

En `.claude/skills/`. El repo de origen está pensado para inversión discrecional
en renta variable US, así que se ha instalado solo lo aplicable a este bot; se
han descartado las que dependen de FMP/FINVIZ de pago o de flujos manuales de
screening (CANSLIM, VCP, dividendos, stockbee, edge-*, kanchi).

| Skill | Para qué aquí |
|---|---|
| `backtest-expert` | Refuerza el gate de §1: robustez de parámetros, slippage, sesgos, sobreajuste |
| `options-strategy-advisor` | Black-Scholes y griegas — es lo que sostiene la calibración del wheel |
| `position-sizer` | Dimensionado por riesgo y ATR, contraste para `NOTIONAL_PCT` e `INITIAL_ALLOCATION` |
| `drawdown-circuit-breaker` | Referencia contra la que contrastar `shared/kill_switch.py` |
| `market-breadth-analyzer`, `uptrend-analyzer` | Filtro de régimen (hallazgo 7) — sin API key |
| `portfolio-manager` | Revisión de cartera vía Alpaca |
| `trade-performance-coach`, `weekly-performance-digest` | El bot no lleva ningún diario de operaciones |
| `exposure-coach` | Techo de exposición neta — se cruza con el hallazgo 6 |
| `pre-trade-discipline-gate`, `trader-memory-core`, `data-quality-checker` | Soporte |

`.gitignore` lleva ahora `!.claude/skills/**/*.json`: la regla global `*.json`
se comía los esquemas y fixtures de las skills.

---

## Verificación

```
325 passed, 1 skipped   (baseline antes de la sesión: 302 passed)
docker compose build    OK
```

Todo cambio de lógica fue en rojo → verde: los tests se escribieron antes que
la implementación en los tres casos (`StreamHandle`, `feasibility`, gate del
kill switch en copy).

**Sin desplegar todavía.** Al reiniciar el contenedor, `trailing_task` verá que
no hay estado y abrirá una posición nueva por ~30 % del buying power en cuanto
el mercado esté abierto. Es una operación real: conviene que sea una decisión
consciente y no un efecto colateral de un `docker compose up -d`.
