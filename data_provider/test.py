from longbridge.openapi import QuoteContext, Config, Period, AdjustType, TradeSessions, OAuthBuilder

# oauth = OAuthBuilder("your-client-id").build(lambda url: print("Visit:", url))
# config = Config.from_oauth(oauth)
LONGBRIDGE_APP_KEY="c0af70052866ffdff592455670df2343"
LONGBRIDGE_APP_SECRET="adcca0c4dace9e34d42b7c1a4b3cf69c47e223b4da4d810ac155e1a50d591272"
LONGBRIDGE_ACCESS_TOKEN="""m_eyJhbGciOiJSUzI1NiIsImtpZCI6ImQ5YWRiMGIxYTdlNzYxNzEiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJsb25nYnJpZGdlIiwic3ViIjoiYWNjZXNzX3Rva2VuIiwiZXhwIjoxNzg5MTIzMjg0LCJpYXQiOjE3ODEzNDcyODQsImFrIjoiYzBhZjcwMDUyODY2ZmZkZmY1OTI0NTU2NzBkZjIzNDMiLCJhYWlkIjoyMTI0OTc3NCwiYWMiOiJsYl9wYXBlcnRyYWRpbmciLCJtaWQiOjI0NTczOTA0LCJzaWQiOiJEcjBUSlNPdktyMlgwN3ByWnE5aVdBPT0iLCJibCI6MCwidWwiOjAsImlrIjoibGJfcGFwZXJ0cmFkaW5nXzIxMjQ5Nzc0In0.IL4B10BKi3wPKm2Z0KGyE2d-NbseHzF1GAcsH5E1YewZ4BH14xb7SHyGiAfVYgqqabrrFKkKcm_SdzC_klhlTuQCX2dC0kGLhoppdIe7EJZKOcG_GroaFWVuqnx4MdYFut1_h50B9D-qv0eavXiuApovRUdbjQNBhxbHohJExgiJgfJNY9Qr-mFJmLiMs9kFapvZ1yvtdamyvj5UKXy6KZHeeXYTglLNCqakNABSnqy_Invptp_IRoUhUBcRUm3NMMmGqVT-h63XOP4vCG1pg3xq7894K7fqDpTLUmrkxZjvtLfUC-F9KIds7NClnQjFfJV9Kg1wNunQJaR84_0w-gRwWBzylLu-txGkAQJMuxyyzmyHzniStRgzrCBetyN-4-87ngt6j3VFo4ciCE52NC98AJMte8SGp92vtrTS06MQIEUvukHaQkuor5QH1ySw3k5QjIRkptn5YpeX9g9I7BX0GlUCEZtwHYTYi10QvfoHWAu37tzCLGSvyhp6T7GW0BHKJrk4DIVICpQWEuhUNK5BBkMeD26T2JrMzrYdCETNR4gmcNSACsut3yeuuZLxY7Wu0NWyNl4GJkWLLLqG0VgtaOfi2WbXyJHSM2SxCUdmOb82nTa2GZaXtoR-T0eyo89stFIMUtpAy9AbPMAS9eYldPfma29rBVggmvqqqjI"""

app_key=LONGBRIDGE_APP_KEY
app_secret=LONGBRIDGE_APP_SECRET
access_token=LONGBRIDGE_ACCESS_TOKEN

config = Config.from_apikey(
                            app_key,
                        app_secret,
                        access_token,
)
ctx = QuoteContext(config)

# Get intraday candlestick data for 700.HK
resp = ctx.candlesticks("700.HK", Period.Day, 10, AdjustType.NoAdjust)
print(resp)

# Get all candlestick data for 700.HK
resp = ctx.candlesticks("700.HK", Period.Day, 10, AdjustType.NoAdjust, trade_sessions=TradeSessions.All)
print(resp)

# Get all candlestick data for 700.HK
# resp = ctx.candlesticks("700.HK", Period.Day, 10, AdjustType.NoAdjust, trade_session=TradeSessions.All)

# from longbridge.openapi import Config, OAuthBuilder

# oauth = OAuthBuilder("fd52fbc5-02a9-47f5-ad30-0842c841aae9").build(
#     lambda url: print(f"Open this URL to authorize: {url}")
# )
# config = Config.from_oauth(oauth)
# ctx = QuoteContext(config)

# # Get intraday candlestick data for 700.HK
# resp = ctx.candlesticks("700.HK", Period.Day, 10, AdjustType.NoAdjust)
# print(resp)
