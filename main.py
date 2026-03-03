from machine import Pin, PWM, SoftI2C
from time import sleep_ms, ticks_ms
import random

# ============================================================
# STILLINGAR
# ============================================================

# I2C (LCD)
I2C_SCL = 21
I2C_SDA = 48

# Hnappar
BTN_A_PIN = 13     # Kasta / Staðfesta
BTN_B_PIN = 41     # Skipta um val

# Pólun hnappa
BTN_A_ACTIVE_LOW = True     # algengt: takki í GND (PULL_UP)
BTN_B_ACTIVE_LOW = False    # þinn B-takki er active-high (PULL_DOWN)

# Hátalari / Buzzer (PWM)
SPEAKER_PIN = 17

# NeoPixel
NEO_PIN = 1
NEO_COUNT = 35

# LCD
LCD_ADDR = 0x27
LCD_ROWS = 2
LCD_COLS = 16

# Leikur
START_LIVES = 3

# Halda báða takka til að endurstilla (ms)
RESET_HOLD_MS = 650

# ============================================================
# BORÐ + STUTTAR SPURNINGAR/SVÖR (LCD-vænar)
# ============================================================

BORÐ = [
    "BYRJUN",         # 0
    "EÐLILEGT",       # 1
    "HINDRUN",        # 2
    "EÐLILEGT",       # 3
    "ÖRYGGI",         # 4 (checkpoint)
    "EÐLILEGT",       # 5
    "FJALL_HLIÐ",     # 6 (þarf slétta tölu >4 => 6)
    "FJALL_SP",       # 7
    "EÐLILEGT",       # 8
    "HÚS",            # 9 (50/50 útrunnið -> -3 næsta kast)
    "HINDRUN",        # 10
    "ÖRYGGI",         # 11
    "LOKA_SP",        # 12
    "MARK",           # 13
]
MARK_INDEX = len(BORÐ) - 1

# Snið: (spurning, A, B, rétturIndex)
# Haltu svörum ultra stuttum (<=4 stafir virkar vel á 16x2)
HINDRUN_SP = [
    ("Plast brotnar?", "Seint", "Hratt", 0),
    ("Fastbui i SA?", "Ja", "Nei", 1),
    ("Is = ferskt?", "Ja", "Nei", 0),
    ("Hlynar hradar?", "Haf", "Land", 1),
]

FJALL_SP = [
    ("Hitinn thar?", "Kalt", "Heit", 0),
    ("Hver byr thar?", "Morg", "Apar", 0),
]

LOKA_SP = [
    ("Minnka CO2?", "Tre", "Olia", 0),
    ("Rusl i nattru?", "Vand", "OK", 0),
]

# ============================================================
# HJÁLPARFÖLL (ENGIN .ljust())
# ============================================================

def fylla(s, breidd):
    if s is None:
        s = ""
    s = str(s)
    if len(s) >= breidd:
        return s[:breidd]
    return s + (" " * (breidd - len(s)))

def klemma(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

# ============================================================
# LCD
# ============================================================

i2c = SoftI2C(scl=Pin(I2C_SCL), sda=Pin(I2C_SDA))
from L2C_LCD import I2cLcd
lcd = I2cLcd(i2c, LCD_ADDR, LCD_ROWS, LCD_COLS)

def lcd_hreinsa():
    lcd.clear()

def lcd_skrifa(l1="", l2=""):
    lcd.move_to(0, 0)
    lcd.putstr(fylla(l1, LCD_COLS))
    lcd.move_to(0, 1)
    lcd.putstr(fylla(l2, LCD_COLS))

# ============================================================
# NeoPixel (áberandi litir fyrir leikmenn)
# ============================================================

import neopixel
np = neopixel.NeoPixel(Pin(NEO_PIN, Pin.OUT), NEO_COUNT)

SLÖKKT = (0, 0, 0)
GOTT   = (0, 255, 0)
SLÆMT  = (255, 0, 0)
VIÐV   = (255, 120, 0)
HVÍTT  = (80, 80, 80)

# Leikmenn: auðþekkjanlegt + mikið andstæða
# L1 = CYAN, L2 = PINK
L1_ST = (0, 255, 255)
L2_ST = (255, 0, 180)

# Dauf baklýsing fyrir umferð
L1_BG = (0, 8, 8)
L2_BG = (8, 0, 6)

def np_hreinsa():
    for i in range(NEO_COUNT):
        np[i] = SLÖKKT
    np.write()

def np_blikka(litur, sinnum=2, on_ms=90, off_ms=70):
    for _ in range(sinnum):
        for i in range(NEO_COUNT):
            np[i] = litur
        np.write()
        sleep_ms(on_ms)
        np_hreinsa()
        sleep_ms(off_ms)

def np_umferð(umferð):
    litur = L1_BG if umferð == 0 else L2_BG
    for i in range(NEO_COUNT):
        np[i] = litur
    np.write()

def pos_i_led(pos):
    if MARK_INDEX <= 0:
        return 0
    return int((pos * (NEO_COUNT - 1)) / MARK_INDEX)

def np_staða(p1_pos, p2_pos, umferð):
    np_umferð(umferð)

    # Öryggisreitir sem dauf hvít merki
    for idx, t in enumerate(BORÐ):
        if t == "ÖRYGGI":
            np[pos_i_led(idx)] = HVÍTT

    led1 = pos_i_led(p1_pos)
    led2 = pos_i_led(p2_pos)

    np[led1] = L1_ST
    np[led2] = L2_ST

    # Ef báðir á sama stað
    if led1 == led2:
        np[led1] = HVÍTT

    np.write()

# ============================================================
# HNAPpar (afristun + pólun) + HALDA BÁÐA TIL AÐ ENDURSTILLA
# ============================================================

class AfnýturTakkі:
    def __init__(self, pin_num, active_low=True, debounce_ms=60):
        self.active_low = active_low
        self.debounce_ms = debounce_ms

        # Réttur pull eftir pólun
        pull = Pin.PULL_UP if active_low else Pin.PULL_DOWN
        self.pin = Pin(pin_num, Pin.IN, pull)

        self._last_state = self.pin.value()
        self._last_change = ticks_ms()

    def _erÝtt(self, v):
        return (v == 0) if self.active_low else (v == 1)

    def ýtt(self):
        now = ticks_ms()
        v = self.pin.value()
        if v != self._last_state and (now - self._last_change) > self.debounce_ms:
            self._last_change = now
            self._last_state = v
            if self._erÝtt(v):
                return True
        return False

takkiA = AfnýturTakkі(BTN_A_PIN, active_low=BTN_A_ACTIVE_LOW)
takkiB = AfnýturTakkі(BTN_B_PIN, active_low=BTN_B_ACTIVE_LOW)

def niðri(t: AfnýturTakkі) -> bool:
    v = t.pin.value()
    return (v == 0) if t.active_low else (v == 1)

_reset_start = None

def endurstilla_haldið():
    """Skilar True EINU SINNI þegar báðir takkar hafa verið haldnir nógu lengi."""
    global _reset_start
    now = ticks_ms()

    if niðri(takkiA) and niðri(takkiB):
        if _reset_start is None:
            _reset_start = now
        elif (now - _reset_start) >= RESET_HOLD_MS:
            _reset_start = None
            return True
    else:
        _reset_start = None

    return False

# ============================================================
# HÁTALARI / TÓNAR + "MISTÖK" Hljóð
# ============================================================

spk = PWM(Pin(SPEAKER_PIN))
spk.duty_u16(0)

def pípa(tíðni=880, ms=80, duty=14000):
    try:
        spk.freq(tíðni)
        spk.duty_u16(duty)
        sleep_ms(ms)
    finally:
        spk.duty_u16(0)

def hljóð_ok():
    pípa(880, 60); sleep_ms(20); pípa(1320, 80)

def hljóð_kast():
    pípa(660, 40); sleep_ms(20); pípa(880, 40)

def hljóð_sigur():
    pípa(784, 70); sleep_ms(25); pípa(988, 70); sleep_ms(25); pípa(1319, 120)

def hljóð_fail():
    pípa(700, 90); sleep_ms(20)
    pípa(520, 110); sleep_ms(20)
    pípa(350, 170)

# Zelda-ish "Item Get"
TONAR = {
    "C6": 1047, "D6": 1175, "E6": 1319, "F6": 1397, "G6": 1568, "A6": 1760, "B6": 1976,
    "C7": 2093, "D7": 2349, "E7": 2637, "F7": 2794, "G7": 3136
}

def spila_lag(seq, duty=16000, gap_ms=15):
    for nóta, lengd in seq:
        if nóta is None:
            spk.duty_u16(0)
            sleep_ms(lengd)
        else:
            spk.freq(TONAR[nóta])
            spk.duty_u16(duty)
            sleep_ms(lengd)
            spk.duty_u16(0)
        sleep_ms(gap_ms)

HLUTUR_LAG = [
    ("E6", 90), ("G6", 90), ("E7", 140),
    ("C7", 140), ("D7", 140), ("G7", 220)
]

# ============================================================
# LEIKSTAÐA + ENDURSTILLING
# ============================================================

leikmenn = [
    {"pos": 0, "öryggi": 0, "líf": START_LIVES, "kast_mod": 0},
    {"pos": 0, "öryggi": 0, "líf": START_LIVES, "kast_mod": 0},
]
umferð = 0

def endurstilla_leik():
    global leikmenn, umferð
    leikmenn = [
        {"pos": 0, "öryggi": 0, "líf": START_LIVES, "kast_mod": 0},
        {"pos": 0, "öryggi": 0, "líf": START_LIVES, "kast_mod": 0},
    ]
    umferð = 0
    np_hreinsa()
    np_umferð(0)
    lcd_skrifa("Endurstilli...", "")
    sleep_ms(400)
    lcd_skrifa("Sudurskaut", "A=Byrja")
    while niðri(takkiA) and niðri(takkiB):
        sleep_ms(10)

def bíða_A():
    while True:
        if endurstilla_haldið():
            endurstilla_leik()
            return
        if takkiA.ýtt():
            return
        sleep_ms(10)

# ============================================================
# LEIKREG
# ============================================================

def staða_lína(i):
    p = leikmenn[i]
    return "L" + str(i + 1) + " " + str(p["pos"]) + " ❤" + str(p["líf"])

def sýna_staða(i, msg=""):
    lcd_skrifa(staða_lína(i), msg[:LCD_COLS])

def missa_líf(i, ástæða="Mistök"):
    leikmenn[i]["líf"] -= 1
    hljóð_fail()
    np_blikka(SLÆMT, sinnum=2)
    sýna_staða(i, ástæða)
    sleep_ms(900)

def senda_á_öryggi(i):
    leikmenn[i]["pos"] = leikmenn[i]["öryggi"]

def spurning(pool):
    sp, a, b, rétt = random.choice(pool)
    val = 0

    while True:
        if endurstilla_haldið():
            endurstilla_leik()
            return False

        a_txt = fylla(a[:4], 4)
        b_txt = fylla(b[:4], 4)

        a_mark = ">" if val == 0 else " "
        b_mark = ">" if val == 1 else " "
        line1 = fylla(sp, LCD_COLS)
        line2 = ("A" + a_mark + a_txt + "  B" + b_mark + b_txt)[:LCD_COLS]
        lcd_skrifa(line1, line2)

        if takkiB.ýtt():
            val = 1 - val
            pípa(1000, 40)

        if takkiA.ýtt():
            pípa(1400, 50)
            return (val == rétt)

        sleep_ms(10)

def fjall_hlið_ok(kast):
    return (kast % 2 == 0) and (kast > 4)  # aðeins 6

def kasta(i):
    p = leikmenn[i]
    base = random.randint(1, 6)
    mod = p["kast_mod"]
    p["kast_mod"] = 0
    val = klemma(base + mod, 1, 6)
    return base, mod, val

def reitur_áhrif(i):
    p = leikmenn[i]
    t = BORÐ[p["pos"]]

    if t == "ÖRYGGI":
        p["öryggi"] = p["pos"]
        np_blikka(HVÍTT, sinnum=1)
        spila_lag(HLUTUR_LAG)
        sýna_staða(i, "Öryggi!")
        sleep_ms(900)

    elif t == "HINDRUN":
        sýna_staða(i, "Spurning")
        np_blikka(VIÐV, sinnum=1)
        sleep_ms(300)
        ok = spurning(HINDRUN_SP)
        if ok:
            hljóð_ok()
            np_blikka(GOTT, sinnum=1)
            sýna_staða(i, "Rétt!")
            sleep_ms(650)
        else:
            missa_líf(i, "Rangt->Öryg")
            senda_á_öryggi(i)

    elif t == "FJALL_SP":
        sýna_staða(i, "Fjall sp.")
        np_blikka(VIÐV, sinnum=1)
        sleep_ms(300)
        ok = spurning(FJALL_SP)
        if ok:
            hljóð_ok()
            np_blikka(GOTT, sinnum=1)
            sýna_staða(i, "Komst!")
            sleep_ms(650)
        else:
            missa_líf(i, "Rangt->Öryg")
            senda_á_öryggi(i)

    elif t == "HÚS":
        sýna_staða(i, "Hus...")
        np_blikka(HVÍTT, sinnum=1)
        sleep_ms(500)
        útrunnið = (random.getrandbits(1) == 1)
        if útrunnið:
            p["kast_mod"] -= 3
            hljóð_fail()
            np_blikka(SLÆMT, sinnum=2)
            sýna_staða(i, "Utrun -3")
        else:
            hljóð_ok()
            np_blikka(GOTT, sinnum=1)
            sýna_staða(i, "Allt ok")
        sleep_ms(850)

    elif t == "LOKA_SP":
        sýna_staða(i, "Loka sp.")
        np_blikka(VIÐV, sinnum=1)
        sleep_ms(300)
        ok = spurning(LOKA_SP)
        if ok:
            hljóð_ok()
            np_blikka(GOTT, sinnum=1)
            sýna_staða(i, "Flott!")
            sleep_ms(650)
        else:
            missa_líf(i, "Rangt->Öryg")
            senda_á_öryggi(i)

def umferð_taka(i):
    if leikmenn[i]["líf"] <= 0:
        return

    np_staða(leikmenn[0]["pos"], leikmenn[1]["pos"], umferð)

    sýna_staða(i, "A=Kasta")
    bíða_A()

    base, mod, val = kasta(i)
    hljóð_kast()

    if mod != 0:
        msg = "Kast " + str(base) + ("+" if mod > 0 else "") + str(mod) + "=" + str(val)
    else:
        msg = "Kast " + str(val)
    sýna_staða(i, msg)
    sleep_ms(850)

    # Fjall-hlið
    if BORÐ[leikmenn[i]["pos"]] == "FJALL_HLIÐ":
        if fjall_hlið_ok(val):
            hljóð_ok()
            np_blikka(GOTT, sinnum=1)
            sýna_staða(i, "Hlið ok")
            sleep_ms(600)
            leikmenn[i]["pos"] = klemma(leikmenn[i]["pos"] + val, 0, MARK_INDEX)
        else:
            missa_líf(i, "Hlið fail")
        reitur_áhrif(i)
        return

    # Venjuleg hreyfing
    leikmenn[i]["pos"] = klemma(leikmenn[i]["pos"] + val, 0, MARK_INDEX)
    sýna_staða(i, "Reitur " + str(leikmenn[i]["pos"]))
    sleep_ms(600)

    reitur_áhrif(i)

def leik_lok():
    for i in range(2):
        if leikmenn[i]["pos"] >= MARK_INDEX:
            lcd_skrifa("L" + str(i+1) + " SIGUR!", "Halda A+B")
            hljóð_sigur()
            np_blikka(GOTT, sinnum=3, on_ms=120, off_ms=80)
            return True

    if leikmenn[0]["líf"] <= 0 and leikmenn[1]["líf"] <= 0:
        lcd_skrifa("Enginn vann :(", "Halda A+B")
        hljóð_fail()
        np_blikka(SLÆMT, sinnum=3, on_ms=120, off_ms=80)
        return True

    return False

# ============================================================
# RÆSING
# ============================================================

lcd_hreinsa()
np_hreinsa()
np_umferð(0)
lcd_skrifa("Sudurskaut", "A=Byrja")
bíða_A()

while True:
    if endurstilla_haldið():
        endurstilla_leik()
        bíða_A()
        continue

    np_staða(leikmenn[0]["pos"], leikmenn[1]["pos"], umferð)

    umferð_taka(umferð)

    if leik_lok():
        while True:
            if endurstilla_haldið():
                endurstilla_leik()
                bíða_A()
                break
            sleep_ms(20)
        continue

    umferð = 1 - umferð
    sleep_ms(250)
    np_umferð(umferð)
    pípa(1100 if umferð == 0 else 800, 60)
