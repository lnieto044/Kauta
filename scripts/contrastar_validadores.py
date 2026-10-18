"""Contrasta los validadores de Kauta con python-stdnum y clabe sobre 55.000 casos aleatorios (válidos e inválidos).
Uso: pip install python-stdnum clabe && python scripts/contrastar_validadores.py
"""
import random, string, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kauta import normalizacion as N
from stdnum.co import nit as s_nit
from stdnum.ar import cuit as s_cuit
from stdnum.mx import rfc as s_rfc
from stdnum.br import cnpj as s_cnpj, cpf as s_cpf
from stdnum.cl import rut as s_rut
from stdnum.pe import ruc as s_ruc
from stdnum.us import rtn as s_aba
from stdnum import iban as s_iban
from stdnum.ar import cbu as s_cbu
import clabe as s_clabe

rnd = random.Random(2026)
def ok(f, v):
    try:
        return bool(f(v))
    except Exception:
        return False
def std(mod, v):
    try:
        mod.validate(v); return True
    except Exception:
        return False

casos = {}
def contrastar(nombre, gen_valido, mutar, kauta, ref, n=2500):
    dif = 0; total = 0
    for _ in range(n):
        v = gen_valido()
        for x in (v, mutar(v)):
            total += 1
            a, b = kauta(x), ref(x)
            if a != b:
                dif += 1
                if dif <= 3: print("  diferencia", nombre, x, "kauta", a, "ref", b)
    casos[nombre] = (total, dif)

dig = lambda k: "".join(rnd.choice(string.digits) for _ in range(k))
def mut_dig(v):
    i = rnd.randrange(len(v)); c = v[i]
    if not c.isdigit(): return v
    return v[:i] + str((int(c) + rnd.randint(1, 9)) % 10) + v[i + 1:]

# NIT (Colombia): base de 9 dígitos + DV
def g_nit():
    b = str(rnd.randint(800000000, 999999999)); return b + s_nit.calc_check_digit(b)
contrastar("NIT", g_nit, mut_dig, lambda v: N.validar_nit(v).valido, lambda v: std(s_nit, v))
# CUIT (Argentina)
def g_cuit():
    b = rnd.choice(["20", "23", "27", "30", "33"]) + dig(8)
    d = s_cuit.calc_check_digit(b)
    return b + d if len(d) == 1 else g_cuit()
def ref_cuit(v):
    # Kauta acepta a propósito los prefijos 25 y 26 (personas, resolución de duplicados), que stdnum no lista
    if v[:2] in ("25", "26") and len(v) == 11 and v.isdigit():
        return s_cuit.calc_check_digit(v[:10]) == v[10]
    return std(s_cuit, v)
contrastar("CUIT", g_cuit, mut_dig, lambda v: N.validar_cuit(v).valido, ref_cuit)
# RFC (México) persona moral (12) y física (13)
HOMO = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
def g_rfc():
    # mezcla de homoclaves posibles e imposibles (primer carácter W, X, Y o Z)
    letras = "ABCDEFGHJKLMNPRSTUVWXYZ"
    b = "".join(rnd.choice(letras) for _ in range(rnd.choice([3, 4])))
    b += f"{rnd.randint(0, 99):02d}{rnd.randint(1, 12):02d}{rnd.randint(1, 28):02d}"
    b += rnd.choice(HOMO + "WXYZ") + rnd.choice(HOMO)
    return b + s_rfc.calc_check_digit(b.rjust(12))
def ref_rfc(v):
    try:
        s_rfc.validate(v, validate_check_digits=True); return True
    except Exception:
        return False
contrastar("RFC", g_rfc, mut_dig, lambda v: N.validar_rfc(v).valido, ref_rfc)
# CPF (Brasil)
def g_cpf():
    b = dig(9)
    if len(set(b)) == 1: return g_cpf()
    return b + s_cpf._calc_check_digits(b)
contrastar("CPF", g_cpf, mut_dig, lambda v: N.validar_cpf(v).valido, lambda v: std(s_cpf, v))
# CNPJ (Brasil, numérico; el alfanumérico se prueba aparte en tests/test_formatos.py)
def g_cnpj():
    b = dig(12); return b + s_cnpj.calc_check_digits(b)
contrastar("CNPJ", g_cnpj, mut_dig, lambda v: N.validar_cnpj(v).valido, lambda v: std(s_cnpj, v))
# RUT (Chile)
def g_rut():
    b = str(rnd.randint(1000000, 29999999)); return b + s_rut.calc_check_digit(b)
contrastar("RUT", g_rut, mut_dig, lambda v: N.validar_rut(v).valido, lambda v: std(s_rut, v))
# RUC (Perú)
def g_ruc():
    b = rnd.choice(["10", "20"]) + dig(8); return b + s_ruc.calc_check_digit(b)
contrastar("RUC", g_ruc, mut_dig, lambda v: N.validar_ruc(v).valido, lambda v: std(s_ruc, v))
# ABA routing (EE. UU.)
def g_aba():
    b = rnd.choice(["0", "1", "2", "3"]) + dig(7); return b + s_aba.calc_check_digit(b)
contrastar("ABA", g_aba, mut_dig, lambda v: N.validar_aba(v).valido, lambda v: std(s_aba, v))
# CBU (Argentina)
def g_cbu():
    b1 = dig(7); b1 += s_cbu.calc_check_digit(b1)
    b2 = dig(13); b2 += s_cbu.calc_check_digit(b2)
    return b1 + b2
contrastar("CBU", g_cbu, mut_dig, lambda v: N.validar_cbu(v).valido, lambda v: std(s_cbu, v))
# CLABE (México)
def g_clabe():
    b = rnd.choice(["002", "012", "014", "021", "030", "036", "044", "058", "072", "127", "137", "646"]) + dig(14)
    return b + str(s_clabe.compute_control_digit(b))
contrastar("CLABE", g_clabe, mut_dig, lambda v: N.validar_clabe(v).valido, lambda v: ok(s_clabe.validate_clabe, v))
# IBAN (varios países)
def g_iban():
    pais = rnd.choice(["DE", "ES", "FR", "GB", "NL", "IT", "BR", "CR", "DO", "SV", "GT"])
    while True:
        cuerpo = {"DE": dig(18), "ES": dig(20), "FR": dig(23), "NL": "ABNA" + dig(10), "IT": rnd.choice(string.ascii_uppercase) + dig(22),
                  "GB": "NWBK" + dig(14), "BR": dig(23) + "C1", "CR": dig(18), "DO": "BAGR" + dig(20), "SV": "CENR" + dig(20), "GT": "TRAJ" + dig(20)}[pais]
        cand = pais + "00" + cuerpo
        try:
            return pais + s_iban.calc_check_digits(cand) + cuerpo
        except Exception:
            continue
def ref_iban(v):
    try:
        s_iban.validate(v); return True
    except Exception:
        return False
def mut_iban(v):
    r = rnd.random()
    if r < 0.5:
        return mut_dig(v)
    # largo equivocado con el control módulo 97 recalculado (solo lo detecta la estructura del país)
    cuerpo = v[4:] + rnd.choice(string.digits) if r < 0.75 else v[4:-1]
    try:
        return v[:2] + s_iban.calc_check_digits(v[:2] + "00" + cuerpo) + cuerpo
    except Exception:
        return mut_dig(v)
contrastar("IBAN", g_iban, mut_iban, lambda v: N.validar_iban(v).valido, ref_iban)

tot = sum(t for t, _ in casos.values()); d = sum(x for _, x in casos.values())
for k, (t, x) in casos.items(): print(f"{k:6s} {t:6d} casos · {x} diferencias")
print("TOTAL", tot, "casos ·", d, "diferencias")
