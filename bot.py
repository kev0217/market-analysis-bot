import os
import json
import asyncio
import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

TOKEN = os.environ["TELEGRAM_TOKEN"].strip()
ARCHIVO = "senales.json"
tareas = set()

MERCADOS = {
    "AAPL": "AAPL", "TSLA": "TSLA",
    "NVDA": "NVDA", "MSFT": "MSFT",
    "EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X",
    "GBP/USD": "GBPUSD=X", "BTC/USD": "BTC-USD",
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

def teclado():
    botones = [
        InlineKeyboardButton(n, callback_data=f"m:{s}")
        for n, s in MERCADOS.items()
    ]
    filas = [botones[i:i + 2] for i in range(0, len(botones), 2)]
    return InlineKeyboardMarkup(filas)

def analizar(ticker):
    try:
        datos = yf.Ticker(ticker).history(period="5d", interval="5m")
        if datos.empty or len(datos) < 50:
            return "Sin datos suficientes (¿mercado cerrado?).", None, None

        cierre = datos["Close"]
        precio = float(cierre.iloc[-1])
        cambio = (precio / cierre.iloc[-2] - 1) * 100
        ema9 = cierre.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = cierre.ewm(span=21, adjust=False).mean().iloc[-1]

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

        alcistas = sum([precio > ema9, ema9 > ema21, rsi > 50])
        sesgo = "alcista" if alcistas >= 2 else "bajista"
        icono = "🟢" if sesgo == "alcista" else "🔴"
        hora = datos.index[-1].strftime("%d/%m %H:%M")

        texto = (
            f"📊 {ticker} · Velas 5m\n"
            f"━━━━━━━━━━━━\n"
            f"Sesgo {sesgo} {icono}\n\n"
            f"💵 Precio: {precio:.4f} ({cambio:+.2f}%)\n"
            f"〰️ EMA 9 / 21: {ema9:.4f} / {ema21:.4f}\n"
            f"📐 RSI: {rsi:.1f} ({senal})\n"
            f"🎯 Indicadores alineados: {alcistas}/3\n"
            f"🕒 Última vela: {hora} UTC\n"
            f"━━━━━━━━━━━━\n"
            f"Registrando señal, resultado en 5 min.\n"
            f"Solo informativo, no es asesoría financiera."
        )
        return texto, precio, sesgo
    except Exception:
        return "Hubo un error al analizar ese mercado.", None, None

def precio_actual(ticker):
    try:
        d = yf.Ticker(ticker).history(period="1d", interval="5m")
        return float(d["Close"].iloc[-1])
    except Exception:
        return None

async def evaluar(message, simbolo, precio, sesgo):
    await asyncio.sleep(300)
    nuevo = await asyncio.to_thread(precio_actual, simbolo)
    if nuevo is None or nuevo == precio:
        await message.reply_text(
            f"⚪ {simbolo}: sin dato nuevo tras 5 min, señal no contada."
        )
        return
    acierto = nuevo > precio if sesgo == "alcista" else nuevo < precio
    registro = cargar()
    registro.append({"simbolo": simbolo, "sesgo": sesgo, "acierto": acierto})
    guardar(registro)
    marca = "✅ Acertó" if acierto else "❌ Falló"
    await message.reply_text(
        f"{marca} · {simbolo} ({sesgo})\n{precio:.4f} → {nuevo:.4f}"
    )

async def enviar_analisis(message, simbolo):
    texto, precio, sesgo = await asyncio.to_thread(analizar, simbolo)
    await message.reply_text(texto, reply_markup=teclado())
    if precio is not None:
        t = asyncio.create_task(evaluar(message, simbolo, precio, sesgo))
        tareas.add(t)
        t.add_done_callback(tareas.discard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋 Elige un mercado, o usa /analiza TICKER y /stats.",
        reply_markup=teclado(),
    )

async def analiza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Elige el mercado:", reply_markup=teclado())
        return
    await enviar_analisis(update.message, context.args[0].upper())

async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await enviar_analisis(q.message, q.data.split(":", 1)[1])

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = cargar()
    if not r:
        await update.message.reply_text("Aún no hay señales evaluadas.")
        return
    total = len(r)
    ok = sum(1 for x in r if x["acierto"])
    await update.message.reply_text(
        f"📈 Señales evaluadas: {total}\n"
        f"✅ Aciertos: {ok} ({ok / total * 100:.1f}%)\n"
        f"❌ Fallos: {total - ok}\n\n"
        f"Con menos de ~100 señales el porcentaje no es confiable."
    )

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("analiza", analiza))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CallbackQueryHandler(boton))
app.run_polling()