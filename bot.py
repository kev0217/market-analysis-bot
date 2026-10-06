import os
import asyncio
import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ["TELEGRAM_TOKEN"]

def analizar(ticker):
    try:
        datos = yf.Ticker(ticker).history(period="6mo")
        if datos.empty:
            return "No encontré ese ticker."

        cierre = datos["Close"]
        precio = cierre.iloc[-1]
        media20 = cierre.tail(20).mean()
        media50 = cierre.tail(50).mean()
        cambio = (precio / cierre.iloc[-2] - 1) * 100

        delta = cierre.diff()
        ganancia = delta.clip(lower=0).rolling(14).mean()
        perdida = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - 100 / (1 + ganancia.iloc[-1] / perdida.iloc[-1])

        tendencia = "alcista 📈" if media20 > media50 else "bajista 📉"
        if rsi > 70:
            senal = "sobrecompra"
        elif rsi < 30:
            senal = "sobreventa"
        else:
            senal = "neutral"

        return (
            f"{ticker.upper()}\n"
            f"Precio: {precio:.2f} ({cambio:+.2f}% hoy)\n"
            f"Media 20d: {media20:.2f} | Media 50d: {media50:.2f}\n"
            f"Tendencia: {tendencia}\n"
            f"RSI: {rsi:.1f} ({senal})\n\n"
            f"Solo informativo, no es asesoría financiera."
        )
    except Exception:
        return "Hubo un error al analizar ese ticker."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋 Usa /analiza seguido de un ticker.\nEjemplo: /analiza AAPL"
    )

async def analiza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analiza AAPL")
        return
    texto = await asyncio.to_thread(analizar, context.args[0])
    await update.message.reply_text(texto)

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("analiza", analiza))
app.run_polling()