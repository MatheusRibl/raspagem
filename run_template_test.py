from app import app

client = app.test_client()
resp = client.get('/')
print('GET / status:', resp.status_code)
# do a POST sample
resp2 = client.post('/', data={'termo':'hungria'})
print('POST / status:', resp2.status_code)
print('len body:', len(resp2.data))
# print first 400 chars
print(resp2.data[:400].decode('utf-8', errors='ignore'))
