"""Web Push (RFC 8030/8291/8292) nur mit der Standardbibliothek: P-256 (ECDH, ECDSA für VAPID), HKDF, AES-128-GCM.
Übernommen aus dem Emden Tigers Hub (server.py), dort geprüft gegen die Testwerte aus RFC 8291 Anhang A und NIST-GCM.
Nachrichten sind Ende-zu-Ende verschlüsselt, der Push-Dienst (Google, Apple, Mozilla) sieht nur Absender-Schlüssel, Größe und Zeitpunkt.
"""
import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlparse

_EC_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_EC_A = _EC_P - 3
_EC_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_EC_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_EC_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
         0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % _EC_P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + _EC_A) * pow(2 * y1, -1, _EC_P) % _EC_P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, _EC_P) % _EC_P
    x3 = (lam * lam - x1 - x2) % _EC_P
    return x3, (lam * (x1 - x3) - y1) % _EC_P


def _ec_mul(k, pt):
    r0, r1 = None, pt   # Montgomery-Leiter: gleiche Schrittfolge für jedes Bit
    for bit in bin(k)[2:]:
        if bit == "1":
            r0, r1 = _ec_add(r0, r1), _ec_add(r1, r1)
        else:
            r0, r1 = _ec_add(r0, r0), _ec_add(r0, r1)
    return r0


def _ec_on_curve(pt):
    x, y = pt
    return 0 <= x < _EC_P and 0 <= y < _EC_P and (y * y - (x * x * x + _EC_A * x + _EC_B)) % _EC_P == 0


def ec_pub_bytes(pt):
    return b"\x04" + pt[0].to_bytes(32, "big") + pt[1].to_bytes(32, "big")


def ec_pub_point(raw):
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError("Ungültiger öffentlicher Schlüssel")
    pt = (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big"))
    if not _ec_on_curve(pt):
        raise ValueError("Schlüssel liegt nicht auf der Kurve")
    return pt


def ec_keypair(priv=None):
    d = priv if priv is not None else secrets.randbelow(_EC_N - 1) + 1
    return d, _ec_mul(d, _EC_G)


def ec_sign(d, data):
    """ECDSA P-256 mit SHA-256, Ergebnis r||s (64 Bytes) wie für JWT ES256 nötig."""
    z = int.from_bytes(hashlib.sha256(data).digest(), "big")
    while True:
        k = secrets.randbelow(_EC_N - 1) + 1
        r = _ec_mul(k, _EC_G)[0] % _EC_N
        if not r:
            continue
        s = pow(k, -1, _EC_N) * (z + r * d) % _EC_N
        if s:
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def ec_verify(pub, data, sig):
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if not (0 < r < _EC_N and 0 < s < _EC_N):
        return False
    z = int.from_bytes(hashlib.sha256(data).digest(), "big")
    w = pow(s, -1, _EC_N)
    pt = _ec_add(_ec_mul(z * w % _EC_N, _EC_G), _ec_mul(r * w % _EC_N, pub))
    return pt is not None and pt[0] % _EC_N == r


# AES-128 (nur Verschlüsseln) und GCM
_AES_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cfd0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdbe0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9ee1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_AES_RCON = (1, 2, 4, 8, 16, 32, 64, 128, 27, 54)


def _aes_expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [_AES_SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= _AES_RCON[i // 4 - 1]
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _aes_block(rk, block):
    s = [b ^ k for b, k in zip(block, rk[0])]
    for rnd in range(1, 11):
        s = [_AES_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]   # ShiftRows (spaltenweise Ablage)
        if rnd != 10:
            t = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                x = a[0] ^ a[1] ^ a[2] ^ a[3]
                t += [a[i] ^ x ^ _xt(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = t
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return bytes(s)


def _gf_mul(x, y):
    r, R = 0, 0xE1 << 120
    for i in range(127, -1, -1):
        if (y >> i) & 1:
            r ^= x
        x = (x >> 1) ^ R if x & 1 else x >> 1
    return r


def aes128_gcm_encrypt(key, iv, plaintext, aad=b""):
    rk = _aes_expand(key)
    h = int.from_bytes(_aes_block(rk, bytes(16)), "big")
    j0 = iv + b"\x00\x00\x00\x01"
    out = bytearray()
    ctr = int.from_bytes(j0, "big")
    for i in range(0, len(plaintext), 16):
        ctr = (ctr & ~0xFFFFFFFF) | ((ctr + 1) & 0xFFFFFFFF)
        ks = _aes_block(rk, ctr.to_bytes(16, "big"))
        out += bytes(a ^ b for a, b in zip(plaintext[i:i + 16], ks))
    def blocks(b):
        b = b + bytes(-len(b) % 16)
        return [int.from_bytes(b[i:i + 16], "big") for i in range(0, len(b), 16)]
    g = 0
    for blk in blocks(aad) + blocks(bytes(out)) + [((len(aad) * 8) << 64) | (len(out) * 8)]:
        g = _gf_mul(g ^ blk, h)
    tag = bytes(a ^ b for a, b in zip(g.to_bytes(16, "big"), _aes_block(rk, j0)))
    return bytes(out) + tag


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    s = str(s or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def webpush_encrypt(ua_public, auth_secret, plaintext, as_priv=None, salt=None):
    """RFC 8291 (aes128gcm): ein Datensatz, Ergebnis ist der fertige Nachrichtenkörper."""
    ua_pt = ec_pub_point(ua_public)
    d, as_pt = ec_keypair(as_priv)
    as_public = ec_pub_bytes(as_pt)
    shared = _ec_mul(d, ua_pt)[0].to_bytes(32, "big")
    salt = salt or secrets.token_bytes(16)
    hm = lambda k, m: hmac.new(k, m, hashlib.sha256).digest()
    ikm = hm(hm(auth_secret, shared), b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = hm(salt, ikm)
    cek = hm(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = hm(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    header = salt + (4096).to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + aes128_gcm_encrypt(cek, nonce, plaintext + b"\x02")


PUSH_HOSTS = (".googleapis.com", ".push.apple.com", ".push.services.mozilla.com", ".notify.windows.com", ".windows.com")


def push_endpoint_ok(url):
    """Nur https-Adressen der bekannten Push-Dienste (sonst könnte jemand den Server an beliebige Adressen schicken lassen)."""
    u = urlparse(str(url or ""))
    host = (u.hostname or "").lower()
    return u.scheme == "https" and len(url) < 1000 and any(host.endswith(h) or host == h.lstrip(".") for h in PUSH_HOSTS)


