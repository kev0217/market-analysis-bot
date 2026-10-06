import yfinance as yf

def analizar(ticker):
    datos = yf.Ticker(ticker).history(period="6mo")
    if datos.empty:
        return "No encontré ese ticker."

    cierre = datos["Close"]
    precio = cierre.iloc[-1]
    media20 = cierre.tail(20).mean()
    media50 = cierre.tail(50).mean()
    cambio = (precio / cierre.iloc[-2] - 1) * 100

    # RSI de 14 días
    delta = cierre.diff()
    ganancia = delta.clip(lower=0).rolling(14).mean()
    perdida = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + ganancia.iloc[-1] / perdida.iloc[-1])

    tendencia = "alcista" if media20 > media50 else "bajista"
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
        f"RSI: {rsi:.1f} ({senal})"
    )

while True:
    t = input("Ticker (ej. AAPL, o 'salir'): ").strip()
    if t.lower() == "salir":
        break
    print(analizar(t), "\n")