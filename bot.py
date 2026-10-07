import os
import json
import asyncio
import pandas as pd
import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

TOKEN = os.environ["TELEGRAM_TOKEN"].strip()
ARCHIVO = "senales.json"
tareas = set()

MERCADOS = {
    "AAPL": "AAPL", "TSLA": "TSLA",
    "NVDA": "NVDA", "MSFT": "MSFT",
    "EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X",
    "GBP/USD": "GBPUSD=X", "BTC/USD": "BTC-USD",
    "ORO": "GC=F", "S&P500": "^GSPC",
}

TEMPORALIDADES = {
    "1m": ("1m", "5d", 60),
    "5m": ("5m", "1mo", 300),
    "15m": ("15m", "2mo", 900),
    "30m": ("30m", "2mo", 1800),
    "1h": ("1h", "1y", None),
    "4h": ("1h", "1y", None),
    "1d": ("1d", "5y", None),
}

def cargar():
    try:
        with open(ARCHIVO) as f:
            return json.load(f)
    except Exception:
        return []

def guardar(lista):
    with open(ARCHIVO, "w") as f:
        json.dump(lista, f)

def normalizar(texto):
    t = texto.strip().upper()
    if t in MERCADOS:
        return MERCADOS[t]
    sin = t.replace("/", "")
    if "/" in t and len(sin) == 6 and sin.isalpha():
        return sin + "=X"
    return t

def teclado_mercados():
    botones = [
        InlineKeyboardButton(n, callback_data=f"m:{s}")
        for n, s in MERCADOS.items()
    ]
    filas = [botones[i:i + 2] for i in range(0, len(botones), 2)]
    return InlineKeyboardMarkup(filas)

def teclado_tf(simbolo):
    botones = [
        InlineKeyboardButton(tf, callback_data=f"t:{simbolo}:{tf}")
        for tf in TEMPORALIDADES
    ]
    filas = [botones[i:i + 4] for i in range(0, len(botones), 4)]
    return InlineKeyboardMarkup(filas)
def analizar(ticker, tf):
    try:
        intervalo, periodo, espera = TEMPORALIDADES[tf]
        datos = yf.Ticker(ticker).history(period=periodo, interval=intervalo)
        if tf == "4h" and not datos.empty:
            datos = datos.resample("4h").agg({"Close": "last"}).dropna()
        if datos.empty or len(datos) < 200:
            return "Sin datos suficientes para la EMA 200 (¿mercado cerrado o ticker inválido?).", None, None

        cierre = datos["Close"]
        precio = float(cierre.iloc[-1])
        cambio = (precio / cierre.iloc[-2] - 1) * 100
        ema50 = cierre.ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = cierre.ewm(span=200, adjust=False).mean().iloc[-1]

        delta = cierre.diff()
        ganancia = delta.clip(lower=0).rolling(14).mean()
        perdida = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - 100 / (1 + ganancia.iloc[-1] / perdida.iloc[-1])

        if rsi > 70:
            senal = "sobrecompra"
        elif rsi < 30:
            senal = "sobreventa"
        else:
            senal = "neutral"

        alcistas = sum([precio > ema50, ema50 > ema200, rsi > 50])
        sesgo = "alcista" if alcistas >= 2 else "bajista"
        icono = "🟢" if sesgo == "alcista" else "🔴"
        hora = datos.index[-1].strftime("%d/%m %H:%M %Z")

        if espera:
            pie = f"Registrando señal, resultado en {espera // 60} min."
        else:
            pie = "Sin evaluación automática en esta temporalidad."

        texto = (
            f"📊 {ticker} · {tf}\n"
            f"━━━━━━━━━━━━\n"
            f"Sesgo {sesgo} {icono}\n\n"
            f"💵 Precio: {precio:.4f} ({cambio:+.2f}%)\n"
            f"〰️ EMA 50 / 200: {ema50:.4f} / {ema200:.4f}\n"
            f"📐 RSI: {rsi:.1f} ({senal})\n"
            f"🎯 Indicadores alineados: {alcistas}/3\n"
            f"🕒 Última vela: {hora}\n"
            f"━━━━━━━━━━━━\n"
            f"{pie}\n"
            f"Solo informativo, no es asesoría financiera."
        )
        return texto, precio, sesgo
    except Exception:
        return "Hubo un error al analizar ese mercado.", None, None

def precio_actual(ticker, tf):
    try:
        intervalo = TEMPORALIDADES[tf][0]
        d = yf.Ticker(ticker).history(period="2d", interval=intervalo)
        return float(d["Close"].iloc[-1])
    except Exception:
        return None

async def evaluar(message, simbolo, tf, precio, sesgo, espera):
    await asyncio.sleep(espera)
    nuevo = await asyncio.to_thread(precio_actual, simbolo, tf)
    if nuevo is None or nuevo == precio:
        await message.reply_text(
            f"⚪ {simbolo} {tf}: sin dato nuevo, señal no contada."
        )
        return
    acierto = nuevo > precio if sesgo == "alcista" else nuevo < precio
    registro = cargar()
    registro.append(
        {"simbolo": simbolo, "tf": tf, "sesgo": sesgo, "acierto": acierto}
    )
    guardar(registro)
    marca = "✅ Acertó" if acierto else "❌ Falló"
    await message.reply_text(
        f"{marca} · {simbolo} {tf} ({sesgo})\n{precio:.4f} → {nuevo:.4f}"
    )
BT_PERIODOS = {
    "1m": ("1m", "7d"),
    "5m": ("5m", "60d"),
    "15m": ("15m", "60d"),
    "30m": ("30m", "60d"),
    "1h": ("1h", "2y"),
    "4h": ("1h", "2y"),
    "1d": ("1d", "10y"),
}

def resumen(sub):
    t = len(sub)
    if t == 0:
        return "sin señales"
    a = int(sub["ok"].sum())
    neto = a * 0.85 - (t - a)
    return f"{a}/{t} ({a / t * 100:.1f}%) · neto {neto:+.1f} u"

def backtest_calc(ticker, tf):
    try:
        intervalo, periodo = BT_PERIODOS[tf]
        datos = yf.Ticker(ticker).history(period=periodo, interval=intervalo)
        if tf == "4h" and not datos.empty:
            datos = datos.resample("4h").agg({"Close": "last"}).dropna()
        if datos.empty or len(datos) < 300:
            return "Sin datos suficientes para el backtest."

        c = datos["Close"]
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()
        delta = c.diff()
        gan = delta.clip(lower=0).rolling(14).mean()
        per = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - 100 / (1 + gan / per)

        score = (
            (c > ema50).astype(int)
            + (ema50 > ema200).astype(int)
            + (rsi > 50).astype(int)
        )
        df = pd.DataFrame({"c": c, "s": score, "n": c.shift(-1)}).iloc[200:-2]
        df = df[df["n"] != df["c"]].copy()
        alc = df["s"] >= 2
        df["ok"] = ((df["n"] > df["c"]) & alc) | ((df["n"] < df["c"]) & ~alc)
        fuertes = df[(df["s"] == 3) | (df["s"] == 0)]

        return (
            f"📊 Backtest {ticker} · {tf}\n"
            f"Velas probadas: {len(df)}\n\n"
            f"Todas las señales:\n{resumen(df)}\n\n"
            f"Solo fuertes (3/3 o 0/3):\n{resumen(fuertes)}\n\n"
            f"Equilibrio con pago 85%: 54.1%\n"
            f"u = unidades apostadas. Sin spread ni comisiones.\n"
            f"Es el pasado, no garantiza nada."
        )
    except Exception:
        return "Error en el backtest."

async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 or context.args[1].lower() not in TEMPORALIDADES:
        await update.message.reply_text("Uso: /backtest EUR/USD 5m")
        return
    simbolo = normalizar(context.args[0])
    tf = context.args[1].lower()
    await update.message.reply_text("Calculando, un momento...")
    texto = await asyncio.to_thread(backtest_calc, simbolo, tf)
    await update.message.reply_text(texto)

async def enviar_analisis(message, simbolo, tf):
    texto, precio, sesgo = await asyncio.to_thread(analizar, simbolo, tf)
    await message.reply_text(texto, reply_markup=teclado_tf(simbolo))
    espera = TEMPORALIDADES[tf][2]
    if precio is not None and espera:
        t = asyncio.create_task(
            evaluar(message, simbolo, tf, precio, sesgo, espera)
        )
        tareas.add(t)
        t.add_done_callback(tareas.discard)

async def pedir_tf(message, simbolo):
    await message.reply_text(
        f"Elige la temporalidad para {simbolo}:",
        reply_markup=teclado_tf(simbolo),
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋 Elige un mercado, o escribe cualquier ticker "
        "(ej. AMZN, ETH-USD, EUR/CHF).\n\n"
        "También: /analiza AMZN 15m, /backtest EUR/USD 5m y /stats",
        reply_markup=teclado_mercados(),
    )

async def analiza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Elige el mercado:", reply_markup=teclado_mercados()
        )
        return
    simbolo = normalizar(context.args[0])
    if len(context.args) > 1 and context.args[1].lower() in TEMPORALIDADES:
        await enviar_analisis(update.message, simbolo, context.args[1].lower())
    else:
        await pedir_tf(update.message, simbolo)

async def texto_libre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if " " in txt or len(txt) > 20:
        await update.message.reply_text("Escribe solo el ticker, ej. AMZN")
        return
    await pedir_tf(update.message, normalizar(txt))

async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    partes = q.data.split(":")
    if partes[0] == "m":
        await pedir_tf(q.message, partes[1])
    elif partes[0] == "t":
        await enviar_analisis(q.message, partes[1], partes[2])

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = cargar()
    if not r:
        await update.message.reply_text("Aún no hay señales evaluadas.")
        return
    total = len(r)
    ok = sum(1 for x in r if x["acierto"])
    lineas = [
        f"📈 Señales evaluadas: {total}",
        f"✅ Aciertos: {ok} ({ok / total * 100:.1f}%)",
        f"❌ Fallos: {total - ok}",
        "",
    ]
    for tf in TEMPORALIDADES:
        sub = [x for x in r if x.get("tf", "5m") == tf]
        if sub:
            a = sum(1 for x in sub if x["acierto"])
            lineas.append(f"{tf}: {a}/{len(sub)} ({a / len(sub) * 100:.0f}%)")
    lineas.append("\nCon menos de ~100 señales el porcentaje no es confiable.")
    await update.message.reply_text("\n".join(lineas))

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("analiza", analiza))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("backtest", backtest))
app.add_handler(CallbackQueryHandler(boton))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_libre))
app.run_polling()