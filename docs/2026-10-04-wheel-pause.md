# Wheel pausada — 2026-10-04

**Qué:** `WHEEL_SCORE_THRESHOLD=0.9` en `.env` (antes 0.15; backup en
`.env.bak.20261004`). El umbral solo filtra la **apertura** de spreads
(`wheel/spreads.py::best_bull_put_spread`), así que el spread abierto
(SOFI 15.5/13.5 P, vence 2026-10-16) se sigue gestionando igual: cierre al 50 %
de la prima o liquidación al vencimiento. Después de eso la wheel se queda IDLE.

**Por qué — EV negativo por construcción:**

- Prima ~$22 contra pérdida máxima ~$178 (= 17 % del equity de ~$1 040 en una
  sola operación, por encima de la tolerancia de -10 % de §1). Break-even ≈ 90 %
  de acierto.
- Asimetría: ganancias topadas al 50 % de la prima (~$11), pérdidas sin stop
  hasta vencimiento.
- Real (15-ago → 4-oct): 3 spreads, **-$59 realizados** (el del 25-sep -$61).
  Copy +$68,7 y trailing +$34,7 en el mismo periodo.
- Simulación de la regla (4 % OTM, $2 de ancho, 15 sesiones, crédito $22,
  mantener a vencimiento) sobre SOFI 2021-06 → 2026-10 con spot ≥ $10:
  45 operaciones, 67 % de acierto, **-$25/operación**, 6 pérdidas máximas.
  Con crédito $30 sigue negativa (-$17/op). No modela el cierre al 50 %, que
  solo recorta las ganancias.
- Nunca tuvo backtest (§1): el 15-ago solo se recalibró para que pudiera abrir.

**Efecto colateral esperado:** tras 40 ciclos secos (~1,5 sesiones)
`wheel/feasibility.py` mandará **una** alerta por Telegram diciendo que el
umbral es inalcanzable. Es intencionado, ignorarla.

**Reactivar:** volver a `WHEEL_SCORE_THRESHOLD=0.15` y
`docker compose up -d --no-build` fuera de horario de mercado. Antes, construir
un backtest de la wheel con precios de opciones reales que pase el gate de §1.
