# test.py
from passlib.context import CryptContext

ctx = CryptContext(schemes=['bcrypt_sha256'])

# Paste chính xác hash đang có trong DB
stored = "$bcrypt-sha256$v=2,t=2b,r=12$wRLcA/fKqq1YktKuj1N.5e$sumnavsvkW/2y10zxNw7nHSg.bsA5Ta"

plain = "12345678"  # Mật khẩu gốc

print("identify:", ctx.identify(stored))
print("verify:  ", ctx.verify(plain, stored))

# Tạo hash mới và verify lại luôn
new_hash = ctx.hash(plain)
print("new hash:", new_hash)
print("verify new:", ctx.verify(plain, new_hash))