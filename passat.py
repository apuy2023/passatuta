#!/usr/bin/env python3

import binascii
import sys
import re
import argparse
import json
from fuzzywuzzy import process
from collections import Counter
import chart_generator as cg

VERSION = "1.7"

SYMBOLS = "~`!@#$%^&*()_\-+=}\]{[|\\\"':;?/>.<, "

stats_regex = {
    "Contains: 123": f"123",
    "Contains: 1234": f"1234",
    "Contains: space": " ",
    "Has: All lowercase": "^[a-z]+$",
    "Has: All num": "^[\d]+$",
    "Has: All uppercase": "^[A-Z]+$",
    "Has: First capital, last number": "^[A-Z].*\d$",
    "Has: First capital, last symbol": f"^[A-Z].*[{SYMBOLS}]$",
    "Has: Four digits at the end": "[^\d]\d\d\d\d$",
    "Has: Single digit at the end": "[^\d]\d$",
    "Has: Three digits at the end": "[^\d]\d\d\d$",
    "Has: Two digits at the end": "[^\d]\d\d$",
    "Has: Upper + lower + num + symbol": f"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[{SYMBOLS}]).*$",
    "Has: Lower + num + symbol": f"^(?=.*[a-z])(?=.*\d)(?=.*[{SYMBOLS}])[a-z\d{SYMBOLS}]*$",
    "Has: Upper + num + symbol": f"^(?=.*[A-Z])(?=.*\d)(?=.*[{SYMBOLS}])[A-Z\d{SYMBOLS}]*$",
    "Has: Upper + lower + num": "^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z\d]*$",
    "Has: Alpha + num":    "^(?=.*[a-zA-Z])(?=.*\d)[A-Za-z\d]*$",
    "Has: Alpha + symbol": f"^(?=.*[a-zA-Z])(?=.*[{SYMBOLS}])[A-Za-z{SYMBOLS}]*$",
    "Has: Upper + lower + symbol": f"^(?=.*[a-z])(?=.*[A-Z])(?=.*[{SYMBOLS}])[A-Za-z{SYMBOLS}]*$",
    "Has: Upper + lower": "^(?=.*[a-z])(?=.*[A-Z])[A-Za-z]*$",
    "Last digit is '0'": "0$",
    "Last digits are '020'": "020$",
    "Last digits are '19xx'": "19\d\d$",
    "Last digits are '20'": "20$",
    "Last digits are '2020'": "2020$",
    "Last digits are '20xx'": "20\d\d$",
    "Seq: 1 upper > lower > num or symbol": f"^[A-Z][a-z]+[\d{SYMBOLS}]+$",
    "Seq: 1 upper > lower > num": f"^[A-Z][a-z]+[\d]+$",
    "Seq: aplha > num > alpha": f"^[A-Za-z]+\d+[A-Za-z]+$",
    "Seq: aplha > num > symbol": f"^[A-Za-z]+\d+[{SYMBOLS}]+$",
    "Seq: aplha > num": "^[A-Za-z]+\d+$",
    "Seq: aplha > symbol > num": f"^[A-Za-z]+[{SYMBOLS}]+\d+$",
}

stats = {k: re.compile(v, re.UNICODE) for (k, v) in stats_regex.items()}

#pat_regex = {
#    "[a-z]": "a",
#    "[A-Z]": "A",
#    "[\d]": "1",
#    f"[{SYMBOLS}]": "@",
#}
#
#pat_subs = {v: re.compile(k, re.UNICODE) for (k, v) in pat_regex.items()}

tr_from = f'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789{SYMBOLS}'
tr_to   =  'aaaaaaaaaaaaaaaaaaaaaaaaaaAAAAAAAAAAAAAAAAAAAAAAAAAA1111111111'.ljust(len(tr_from), '@')
trans = str.maketrans(tr_from, tr_to)

#hex_re = re.compile("^\$HEX\[([0-9a-fA-F]*)\]$", re.UNICODE)

line_re = re.compile("(?:.*?:)?(?:.*?:)?(.*)$", re.UNICODE)


def print_counter(title, cnt, grand_total, limit=10):
    print(f"{title}")
    print("=" * len(title))
    items = cnt.most_common(limit)
    if not items:
        print("---- no data ----")
        print("")
        return
    max_width = max([len(str(i[0])) for i in items])
    for i in cnt.most_common(limit):
        value = i[1]
        percentage = 1.0 * value / grand_total
        print(f"{i[0]:<{max_width}}  {i[1]:>6}  {percentage:>6.1%}")
    print("")


def progbar(curr, total, full_progbar=40):
    frac = curr * 100 // total
    if frac == progbar.last_frac:
        return
    progbar.last_frac = frac

    filled_progbar = ('#' * (frac * full_progbar // 100)).ljust(full_progbar)
    msg = 'Completed: [' + filled_progbar + '] ' + '[{:>3d}%]'.format(frac)
    print(msg, end='\r')
    #sys.stdout.flush()

progbar.last_frac = -1


def main():
    parser = argparse.ArgumentParser(
        description=f"Audit password quality v{VERSION}")
    parser.add_argument("input_file", type=str,
                        default=['-'], nargs="*",
                        help="input file names, one password per line. If ommited, read from stdin")
    parser.add_argument("-v", "--verbose", help="increase output verbosity",
                        action="store_true")
    parser.add_argument("-f", "--freq", help="run frequency analysis for characters used",
                        action="store_true")
    parser.add_argument("--no-categories", help="don't perform fuzzy categorization, improves performance",
                        action="store_true")
    parser.add_argument("-c", "--categories", help="json file with password categories for fuzzy matching, defaults to categories.json",
                        default="categories.json")
    parser.add_argument("-o", "--output", help="output path for the charts. Default: ./images",
                        default="images")
    args = parser.parse_args()

    if not args.no_categories:
        word2category = {}
        with open(args.categories, "r") as read_file:
            categories = json.load(read_file)
        words = set([x for y in categories.values() for x in y])
        for w in words:
            cats = []
            for c, v in categories.items():
                if w in v:
                    cats.append(c)
            word2category[w] = cats

    verbose = args.verbose
    cnt = Counter()
    cnt_length = Counter()
    cnt_pwd = Counter()
    cnt_root = Counter()
    cnt_regex = Counter()
    cnt_symbol = Counter()
    cnt_alpha = Counter()
    cnt_num = Counter()
    cnt_totals = Counter()
    cnt_pattern = Counter()

    sys.stdin.reconfigure(errors='replace')

    grand_total = 0
    total_valid_passwords = 0
    for f in args.input_file:
        print(f"Reading: {f}")
        if f == '-':
            f = sys.stdin.fileno()
        with open(f, 'r', errors='replace') as f:
            # to avoid newlines
            lines = f.read().splitlines()

        total = len(lines)
        print(f"Processing: {total} passwords")
        progress = 0
        valid_passwords = 0
        for l in lines:
            progress += 1

            # process line formats:
            # password
            # user:password
            # user:hash:password
            # ... and extract password only
            p = line_re.match(l).group(1)

            # skip empty passwords
            if not p:
                continue

            valid_passwords += 1

            # convert $HEX[abcd1234] passwords
            # m = hex_re.match(p)
            if p.startswith("$HEX[") and p[-1] == "]":
                p = binascii.unhexlify(p[5:-1]).decode("latin1")

            # length stats
            cnt_length[len(p)] += 1

            # same password counting
            cnt_pwd[p] += 1
            if verbose:
                print(p)

            # letter frequency analysis
            if args.freq:
                cnt_totals["chars"] += len(p)
                for letter in p:
                    if letter.isnumeric():
                        cnt_num[letter] += 1
                        cnt_totals["num"] += 1
                    elif letter.isalpha():
                        cnt_alpha[letter] += 1
                        cnt_totals["alpha"] += 1
                    else:
                        cnt_symbol[letter] += 1
                        cnt_totals["symbol"] += 1

            # pattern counting
            #pwd_pat = p
            #for subst, pat in pat_subs.items():
            #    pwd_pat = pat.sub(subst, pwd_pat)
            pwd_pat = p.translate(trans)
            cnt_pattern[pwd_pat] += 1

            # Matching various regex categories
            for cat, pat in stats.items():
                if pat.search(p):
                    cnt_regex[cat] += 1
                    if verbose:
                        print(cat)

            # Fuzzy matching to categories
            if len(p) > 3 and not args.no_categories and words:
                #highest = process.extractOne(p, words)
                mall = process.extract(p, words)
                if verbose:
                    print(mall)
                pw_categories = set()
                for m in mall:
                    if verbose:
                        print(f"{p} > {m[0]} : {m[1]}")
                    if m[1] > 80:
                        cnt_root[m[0]] += 1
                        pw_categories.update(word2category[m[0]])

                if not pw_categories:
                    pw_categories = ['no_category']

                #print(f">>>> {pw_match} {score} {pw_categories}")
                for pw_category in pw_categories:
                    cnt[pw_category] += 1
                if verbose:
                    print(f"{p} > {pw_categories}")
                    #print(f"'{p}'", highest, pw_category)

            if verbose:
                print()
            else:
                progbar(progress, total)

        grand_total += total
        total_valid_passwords += valid_passwords
        print()

    print()
    print(f"Total lines processed: {grand_total}")
    print(f"Valid passwords found: {total_valid_passwords}")
    print()
    if not args.no_categories:
        print_counter("Categories", cnt, grand_total)
        df = cg.generate_df(cnt=cnt, grand_total = grand_total, limit=15)[1:]
        chart = cg.generate_barchart(df=df, title = "Categorías más repetidas", x="value", y="desc", x_label = "Ocurrencias", y_label = "Categoría")
        cg.export(chart, title = "categorias_mas_repetidas", output_path=args.output)

        print_counter("Password base words:", cnt_root, grand_total)
        df = cg.generate_df(cnt=cnt_root, grand_total = grand_total, limit=15)
        chart = cg.generate_barchart(df=df, title = "Palabras de diccionario más repetidas", x="value", y="desc", x_label = "Ocurrencias", y_label = "Palabra")
        cg.export(chart, title = "palabras_mas_repetidas", output_path=args.output)

    print_counter("Password length frequency:", cnt_length, grand_total)
    df = cg.generate_df(cnt=cnt_length, grand_total = grand_total)
    df.sort_values(by=["desc"], inplace=True)
    pallete = {}
    for q in set(df["desc"]):
        if q < 8:
            pallete[q] = '#D3212C'
        elif q < 12:
            pallete[q] = '#FF681E'
        else:
            pallete[q] = '#069C56'
    chart = cg.generate_barchart(df=df, title = "Frecuencia de longitud de contraseñas:", x="desc", y="value", x_label = "Número de caracteres", y_label = "Ocurrencias", palette=pallete)
    cg.export(chart, title = "num_caracteres", output_path=args.output)

    print_counter("Password values:", cnt_pwd, grand_total)
    # df = cg.generate_df(cnt=cnt_pwd, grand_total = grand_total, limit=16)[1:]
    df = cg.generate_df(cnt=cnt_pwd, grand_total = grand_total, limit=15)
    chart = cg.generate_barchart(df=df, title = "Contraseñas más repetidas", x="value", y="desc", x_label = "Ocurrencias", y_label = "Contraseña")
    cg.export(chart, title = "cont_mas_repetidos", output_path=args.output)

    print_counter("Charsets and sequences:", cnt_regex, grand_total, limit=10)
    df = cg.generate_df(cnt=cnt_regex, grand_total = grand_total, limit=10)
    df = df[df["desc"].str.contains('Seq')]
    chart = cg.generate_barchart(df=df, title = "Secuencias más repetidas", x="value", y="desc", x_label = "Ocurrencias", y_label = "Secuencia")
    cg.export(chart, title = "sec_mas_repetidos", output_path=args.output)

    print_counter("Password patterns:", cnt_pattern, grand_total, 10)
    df = cg.generate_df(cnt=cnt_pattern, grand_total = grand_total, limit=10)
    chart = cg.generate_barchart(df=df, title = "Patrones más repetidos", x="value", y="desc", x_label = "Ocurrencias", y_label = "Patrón")
    cg.export(chart, title = "patrones_mas_repetidos", output_path=args.output)

    if args.freq:
        print_counter("Most frequent alpha chars:",
                      cnt_alpha, cnt_totals["alpha"])
        print_counter("Most frequent num chars:", cnt_num, cnt_totals["num"])
        print_counter("Most frequent symbol chars:",
                      cnt_symbol, cnt_totals["symbol"])


if __name__ == '__main__':
    main()
