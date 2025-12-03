# app.py - completo
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import os
import math
import requests
from bs4 import BeautifulSoup
from textblob import TextBlob
from deep_translator import GoogleTranslator
import pymysql
import traceback
import time
from urllib.parse import quote_plus, urlparse, unquote, parse_qs

# Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "troque_essa_chave_em_producao")

# ---------------------------
# Banco de dados
# ---------------------------
def conectar_banco():
    """
    Conecta ao MySQL usando variáveis de ambiente:
      DB_HOST (default 'localhost')
      DB_USER (default 'root')
      DB_PASSWORD (default '')
      DB_NAME (default 'noticias')
    Retorna conexão pymysql ou None em caso de erro.
    """
    host = os.getenv('DB_HOST', 'localhost')
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', 'ceub123456')
    db = os.getenv('DB_NAME', 'mop_mvp')

    try:
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=db,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.Cursor,
            connect_timeout=5
        )
        return conn
    except Exception as e:
        print("Erro conectar_banco:", e)
        return None

# ---------------------------
# Utilitárias (links, título, heurísticas)
# ---------------------------
def limpar_link_google(url: str) -> str:
    try:
        if not url:
            return url
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if 'q' in qs and qs['q']:
            return qs['q'][0]
        if '/url?q=' in url:
            part = url.split('/url?q=', 1)[1]
            real = part.split('&', 1)[0]
            return unquote(real)
        return url
    except Exception:
        return url

def normalize_link(link, prefer_domain=None):
    if not link:
        return None
    try:
        if "/url?q=" in link:
            link = limpar_link_google(link)
        if 'busca/click' in link or '/busca?' in link:
            return None
        if link.startswith('/') and prefer_domain:
            link = prefer_domain.rstrip('/') + link
        parsed = urlparse(link)
        if not parsed.scheme:
            link = 'https://' + link
            parsed = urlparse(link)
        if 'google.' in parsed.netloc and not ('news' in parsed.path or 'g1.globo.com' in link):
            if '/url' in parsed.path and 'q=' in parsed.query:
                link = limpar_link_google(link)
                parsed = urlparse(link)
            else:
                return None
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return clean
    except Exception:
        return None

def extract_title_from_url(link):
    try:
        parsed = urlparse(link)
        path = parsed.path or ''
        if not path or path == '/':
            return parsed.netloc
        segs = [s for s in path.split('/') if s]
        last = segs[-1]
        last = unquote(last)
        last = last.split('.')[0]
        title = last.replace('-', ' ').replace('_', ' ')
        if len(title) < 3 or all(c.isdigit() for c in title):
            return parsed.netloc
        return ' '.join([w.capitalize() for w in title.split()])
    except Exception:
        return link

def is_probably_article(title, link):
    if not link:
        return False
    try:
        parsed = urlparse(link)
        if not parsed.scheme or not parsed.netloc:
            return False
        blacklist = ['facebook.com', 'twitter.com', 't.co', 'instagram.com', 'youtube.com',
                     'accounts.google.com', 'accounts.spotify.com', 'linkedin.com', 'bit.ly', 'tinyurl.com', 'meet.google.com']
        net = parsed.netloc.lower()
        if any(b in net for b in blacklist):
            return False
        path = (parsed.path or '').strip('/')
        if '/noticia/' in link or 'g1.globo.com' in parsed.netloc:
            if len(path) < 3:
                return False
        if any(x in link for x in ['busca', 'click', '/search', 'query=']):
            return False
    except Exception:
        return False

    if not title:
        return False
    if title.startswith('http') or '=' in title or '%' in title:
        derived = extract_title_from_url(link)
        if not derived or len(derived) < 3:
            return False
        title = derived
    if '.' in title and ' ' not in title:
        return False
    if len(title) < 6:
        return False
    words = [w for w in title.split() if any(c.isalpha() for c in w)]
    if len(words) < 2:
        return False
    return True

# ---------------------------
# Sentimento
# ---------------------------
def analisar_sentimento(texto: str) -> str:
    try:
        if not texto:
            return 'neutro'
        try:
            translated = GoogleTranslator(source='auto', target='en').translate(texto)
        except Exception:
            translated = texto
        polarity = TextBlob(translated).sentiment.polarity
        if polarity > 0.1:
            return 'positivo'
        if polarity < -0.1:
            return 'negativo'
        return 'neutro'
    except Exception:
        return 'neutro'

# ---------------------------
# Raspagens (mantive seu código)
# ---------------------------
def raspar_g1_requests(termo, limite=20):
    resultados = []
    try:
        q = quote_plus(termo)
        url = f"https://g1.globo.com/busca/?q={q}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        a_tags = soup.select("a.widget--info__title") or soup.select("a.feed-post-link") or soup.select("a[href*='/noticia/']")
        seen = set()
        for a in a_tags:
            raw_link = a.get("href", "") or ""
            link = normalize_link(raw_link, prefer_domain='https://g1.globo.com')
            if not link:
                continue
            titulo = a.get_text(strip=True) or a.get('title') or a.get('aria-label') or ''
            if not titulo:
                parent = a.find_parent()
                if parent:
                    h = parent.find(['h1', 'h2', 'h3'])
                    if h:
                        titulo = h.get_text(strip=True)
            if not titulo or titulo.startswith('http') or len(titulo) < 4:
                titulo = extract_title_from_url(link)
            if not is_probably_article(titulo, link):
                continue
            key = (titulo[:140], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": titulo, "link": link, "orig_link": raw_link or link, "fonte": "G1"})
            if len(resultados) >= limite:
                break
    except Exception as e:
        print("Erro raspar_g1_requests:", e)
        traceback.print_exc()
    print(f"✅ G1 (requests) encontrou: {len(resultados)}")
    return resultados

def raspar_google_requests(termo, limite=12):
    resultados = []
    try:
        q = quote_plus(termo)
        url = f"https://www.google.com/search?q={q}&tbm=nws&hl=pt-BR"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "pt-BR,pt;q=0.9"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        blocos = soup.select("div.dbsr") or soup.select("g-card") or soup.select("div.Gx5Zad")
        if not blocos:
            blocos = soup.select("a[href^='/url?q=']")
        seen = set()
        for b in blocos:
            a = b.find("a") if b.find("a") else (b if b.name == "a" else None)
            link_raw = a.get("href", "") if a else ""
            link = normalize_link(link_raw)
            if not link:
                continue
            title_elem = b.select_one("div.JheGif.nDgy9d") or b.select_one("div.MBeuO span") or b.select_one("h3")
            title = title_elem.get_text(" ", strip=True) if title_elem else ''
            if not title or title.startswith('http') or len(title) < 4:
                title = extract_title_from_url(link)
            if not is_probably_article(title, link):
                continue
            key = (title[:140], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": title, "link": link, "orig_link": link_raw or link, "fonte": "Google Notícias"})
            if len(resultados) >= limite:
                break
    except Exception as e:
        print("Erro raspar_google_requests:", e)
        traceback.print_exc()
    print(f"✅ Google (requests) encontrou: {len(resultados)}")
    return resultados

def raspar_g1(termo):
    res = raspar_g1_requests(termo, limite=12)
    if res:
        return res
    try:
        print("⚠️ G1 via requests não retornou — tentando Selenium como fallback...")
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import time
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=options)
        url = f"https://g1.globo.com/busca/?q={quote_plus(termo)}"
        driver.get(url)
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()
        resultados = []
        a_tags = soup.select("a.widget--info__title") or soup.select("a.feed-post-link") or soup.select("a[href*='/noticia/']")
        if not a_tags:
            a_tags = [a for a in soup.find_all('a', href=True) if ('g1.globo.com' in a.get('href','') or '/noticia/' in a.get('href',''))]
        seen = set()
        for a in a_tags:
            raw_link = a.get('href', '')
            link = normalize_link(raw_link, prefer_domain='https://g1.globo.com')
            if not link:
                continue
            titulo = (a.get_text(strip=True) or a.get('title') or a.get('aria-label') or '').strip()
            if not titulo and a.find('img') and a.find('img').get('alt'):
                titulo = a.find('img').get('alt').strip()
            if not titulo:
                parent = a.find_parent()
                if parent:
                    h = parent.find(['h1', 'h2', 'h3', 'h4'])
                    if h:
                        titulo = h.get_text(strip=True)
            titulo = titulo or extract_title_from_url(link)
            if not is_probably_article(titulo, link):
                continue
            key = (titulo[:120], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": titulo, "link": link, "orig_link": raw_link or link, "fonte": "G1"})
            if len(resultados) >= 8:
                break
        print(f"✅ G1 (selenium fallback) encontrou: {len(resultados)}")
        return resultados
    except Exception as e:
        print("Fallback Selenium G1 falhou:", e)
        traceback.print_exc()
        return []

def raspar_google_noticias(termo):
    res = raspar_google_requests(termo, limite=12)
    if res:
        return res
    try:
        print("⚠️ Google (requests) não retornou — tentando Selenium como fallback...")
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import time
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=options)
        driver.get(f"https://www.google.com/search?q={quote_plus(termo)}&tbm=nws")
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()
        resultados = []
        blocos = soup.select("div.SoaBEf") or soup.select("div.dbsr")
        seen = set()
        for b in blocos:
            a = b.find('a')
            raw_link = a.get('href') if a else ''
            link = normalize_link(raw_link)
            if not link:
                continue
            title_elem = b.select_one("div.MBeuO span") or b.select_one("div.JheGif") or b.select_one("h3")
            title = title_elem.get_text(strip=True) if title_elem else ''
            if not title or title.startswith('http') or len(title) < 4:
                title = extract_title_from_url(link)
            key = (title[:140], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": title, "link": link, "fonte": "Google Notícias"})
            if len(resultados) >= 12:
                break
        print(f"✅ Google (selenium fallback) encontrou: {len(resultados)}")
        return resultados
    except Exception as e:
        print("Fallback Selenium Google falhou:", e)
        traceback.print_exc()
        return []

# ---------------------------
# Salvar notícias no banco (mantido)
# ---------------------------
def salvar_no_banco(resultados, termo):
    if not resultados:
        print("Nenhum resultado para salvar no banco.")
        return
    conexao = conectar_banco()
    if not conexao:
        print("Não conectou ao banco, pulando salvamento.")
        return
    try:
        with conexao.cursor() as cursor:
            for noticia in resultados:
                sentimento = analisar_sentimento(noticia["titulo"])
                try:
                    cursor.execute("""
                        INSERT INTO noticias (titulo, link, fonte, sentimento, termo)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (noticia["titulo"], noticia["link"], noticia.get("fonte",""), sentimento, termo))
                except Exception as e:
                    print("Erro inserção (continuando):", e)
        conexao.commit()
        conexao.close()
        print("💾 Salvou no banco (ou tentou inserir).")
    except Exception as e:
        print("Erro ao salvar no banco:", e)
        traceback.print_exc()

# ---------------------------
# Rotas: register / login / logout / onboarding / index / api
# ---------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not (nome and email and senha):
            flash("Preencha todos os campos.", "erro")
            return redirect(url_for("register"))

        conexao = conectar_banco()
        if not conexao:
            flash("Erro ao conectar no banco.", "erro")
            return redirect(url_for("register"))

        try:
            with conexao.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
                if cursor.fetchone():
                    flash("Email já cadastrado!", "erro")
                    return redirect(url_for("register"))
                senha_hash = generate_password_hash(senha)
                cursor.execute("""
                    INSERT INTO users (nome, email, senha)
                    VALUES (%s, %s, %s)
                """, (nome, email, senha_hash))
            conexao.commit()
            conexao.close()
            flash("Cadastro realizado com sucesso! Faça login.", "sucesso")
            return redirect(url_for("login"))
        except Exception as e:
            print("Erro ao cadastrar:", e)
            traceback.print_exc()
            flash("Erro ao cadastrar usuário.", "erro")
            return redirect(url_for("register"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not (email and senha):
            flash("Preencha email e senha.", "erro")
            return redirect(url_for("login"))

        conexao = conectar_banco()
        if not conexao:
            flash("Erro ao conectar banco.", "erro")
            return redirect(url_for("login"))

        try:
            with conexao.cursor() as cursor:
                cursor.execute("""
                    SELECT id, nome, senha, tema, resultados_por_pagina, fez_onboarding
                    FROM users
                    WHERE email=%s
                """, (email,))
                user = cursor.fetchone()
            conexao.close()

            if not user:
                flash("Email ou senha incorretos!", "erro")
                return redirect(url_for("login"))

            user_id, user_name, user_hash, tema, resultados_por_pagina, fez_onboarding = user

            if not check_password_hash(user_hash, senha):
                flash("Email ou senha incorretos!", "erro")
                return redirect(url_for("login"))

            # set session
            session['user_id'] = user_id
            session['user_name'] = user_name
            session['tema'] = tema or 'claro'
            session['resultados'] = resultados_por_pagina or 12

            # Se não fez onboarding, redireciona para /onboarding
            if fez_onboarding == 0:
                return redirect(url_for("onboarding"))

            flash(f"Bem-vindo(a), {user_name}!", "sucesso")
            return redirect(url_for("index"))

        except Exception as e:
            print("Erro login:", e)
            traceback.print_exc()
            flash("Erro ao fazer login.", "erro")
            return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu da conta.", "sucesso")
    return redirect(url_for("login"))

@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conexao = conectar_banco()
    if not conexao:
        flash("Erro ao conectar no banco.", "erro")
        return redirect(url_for("index"))

    if request.method == "POST":
        tema = request.form.get("tema", "claro")
        try:
            resultados = int(request.form.get("resultados", 12))
        except Exception:
            resultados = 12

        try:
            with conexao.cursor() as cursor:
                cursor.execute("""
                    UPDATE users
                    SET fez_onboarding = 1,
                        tema = %s,
                        resultados_por_pagina = %s
                    WHERE id = %s
                """, (tema, resultados, user_id))
            conexao.commit()
            conexao.close()

            # Atualiza sessão
            session["tema"] = tema
            session["resultados"] = resultados

            flash("Preferências salvas.", "sucesso")
            return redirect(url_for("index"))
        except Exception as e:
            print("Erro ao salvar onboarding:", e)
            traceback.print_exc()
            flash("Erro ao salvar preferências.", "erro")
            return redirect(url_for("onboarding"))

    return render_template("onboarding.html")

@app.route("/", methods=["GET", "POST"])
def index():
    # exige autenticação
    if "user_id" not in session:
        return redirect(url_for("login"))

    # garante que, se ainda não fez onboarding (caso muda manualmente), redirecione
    conexao = conectar_banco()
    if conexao:
        try:
            with conexao.cursor() as cursor:
                cursor.execute("SELECT fez_onboarding FROM users WHERE id=%s", (session["user_id"],))
                status = cursor.fetchone()
            conexao.close()
            if status and status[0] == 0:
                return redirect(url_for("onboarding"))
        except Exception:
            pass

    resultados = []
    sentimentos = {"positivo": 0, "negativo": 0, "neutro": 0}
    termo = ""
    page = int(request.args.get('page', 1) or 1)
    per_page = int(request.args.get('per_page', session.get('resultados', 12) or 12) or 12)
    sources = request.values.getlist('sources') or []
    source_filter = request.args.get('source', '').strip()

    if request.method == "POST":
        termo = (request.form.get("termo") or request.form.get("palavra_chave") or "").strip()
        if termo:
            resultados_g1 = raspar_g1(termo)
            time.sleep(0.3)
            resultados_google = raspar_google_noticias(termo)
            seen_links = set()
            resultados_comb = []
            for r in (resultados_g1 + resultados_google):
                link = r.get("link","")
                if link in seen_links:
                    continue
                seen_links.add(link)
                r["sentimento"] = analisar_sentimento(r.get("titulo",""))
                resultados_comb.append(r)
            resultados = resultados_comb
            # salvar no banco condicional
            if os.getenv('SAVE_TO_DB', '0') == '1':
                salvar_no_banco(resultados, termo)
            for noticia in resultados:
                s = noticia.get("sentimento","neutro")
                sentimentos[s] += 1

    if sources:
        lower_sources = [s.lower() for s in sources]
        resultados = [r for r in resultados if any(ls in (r.get('fonte') or '').lower() for ls in lower_sources)]
    elif source_filter:
        resultados = [r for r in resultados if (r.get('fonte') or '').lower().find(source_filter.lower()) != -1]

    total = len(resultados)
    total_pages = max(1, math.ceil(total / per_page))
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = resultados[start:end]

    return render_template("index.html",
                           resultados=page_items,
                           sentimentos=sentimentos,
                           termo=termo,
                           page=page,
                           per_page=per_page,
                           total=total,
                           total_pages=total_pages,
                           source_filter=source_filter,
                           sources=sources,
                           user_name=session.get('user_name'),
                           tema=session.get('tema'))

@app.route('/api/search')
def api_search():
    termo = (request.args.get('termo') or '').strip()
    page = int(request.args.get('page', 1) or 1)
    per_page = int(request.args.get('per_page', 12) or 12)
    source_filter = request.args.get('source', '').strip()

    resultados = []
    if termo:
        resultados_g1 = raspar_g1(termo)
        resultados_google = raspar_google_noticias(termo)
        seen_links = set()
        for r in (resultados_g1 + resultados_google):
            link = r.get('link','')
            if link in seen_links:
                continue
            seen_links.add(link)
            r['sentimento'] = analisar_sentimento(r.get('titulo',''))
            resultados.append(r)

    if source_filter:
        resultados = [r for r in resultados if (r.get('fonte') or '').lower().find(source_filter.lower()) != -1]

    total = len(resultados)
    total_pages = max(1, math.ceil(total / per_page))
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = resultados[start:end]

    return jsonify({
        'termo': termo,
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
        'results': page_items
    })

@app.route('/health')
def health():
    return 'ok'

if __name__ == "__main__":
    app.run(debug=True)

# app.py - Parte 2/3
# Funções para raspagem com seletores atualizados e validação de links

def raspar_g1_requests(termo, limite=20):
    """
    Raspagem G1 usando requests. Tenta vários seletores e valida link.
    """
    resultados = []
    try:
        q = quote_plus(termo)
        url = f"https://g1.globo.com/busca/?q={q}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # tentativa de seletores - cobrir variações
        selectors = [
            "a.widget--info__title",         # antigo padrão
            "a.feed-post-link",              # antigo padrão
            "a[href*='/noticia/']",          # link contendo /noticia/
            "article a",                     # fallback: anchor dentro de article
            "div.search-body a",             # variações
            "h3 a"                           # manchetes dentro de h3
        ]

        anchors = []
        for sel in selectors:
            found = soup.select(sel)
            if found:
                anchors.extend(found)
        # dedupe anchors by href
        seen_hrefs = set()
        filtered_anchors = []
        for a in anchors:
            href = a.get('href') or a.get('data-href') or ''
            if not href:
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            filtered_anchors.append(a)

        seen = set()
        for a in filtered_anchors:
            raw_link = a.get('href') or a.get('data-href') or ''
            if not raw_link:
                continue
            # preserve prefer domain to build relative links
            link = normalize_link(raw_link, prefer_domain='https://g1.globo.com')
            if not link:
                # if normalize filtered, try to form absolute with g1 domain
                link = urljoin('https://g1.globo.com', raw_link)
                link = normalize_link(link, prefer_domain='https://g1.globo.com')
            if not link:
                continue

            # Get title: try text of anchor, then nearby headings
            titulo = a.get_text(strip=True) or a.get('title') or ''
            if not titulo:
                parent = a.find_parent()
                if parent:
                    h = parent.find(['h1', 'h2', 'h3', 'h4'])
                    if h:
                        titulo = h.get_text(strip=True)
            if not titulo:
                titulo = extract_title_from_url(link)

            # validate heuristics
            if not is_probably_article(titulo, link):
                # debug prints temporarily (comment depois)
                # print("G1 - ignorado (heurística):", titulo, link)
                continue

            # verify link exists (avoid 404s)
            if not url_existente(link):
                # print("G1 - link 404 ou inacessível:", link)
                continue

            key = (titulo[:140], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": titulo, "link": link, "orig_link": raw_link or link, "fonte": "G1"})
            if len(resultados) >= limite:
                break

    except Exception as e:
        print("Erro raspar_g1_requests:", e)
        traceback.print_exc()

    # fallback quick log
    # print(f"✅ G1 (requests) encontrou: {len(resultados)}")
    return resultados

def raspar_google_requests(termo, limite=12):
    """
    Raspagem de Google Notícias via search tbm (tbm=nws).
    Usa vários seletores e normaliza links.
    """
    resultados = []
    try:
        q = quote_plus(termo)
        url = f"https://www.google.com/search?q={q}&tbm=nws&hl=pt-BR"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "pt-BR,pt;q=0.9"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Google estrutura varia. Tente blocos comuns
        blocks = soup.select("div.dbsr") or soup.select("g-card") or soup.select("div.xuvV6b") or soup.select("div.SoaBEf")
        anchors = []
        for b in blocks:
            a = b.find('a')
            if a:
                anchors.append(a)
        # fallback: any a with /url?q=
        if not anchors:
            anchors = soup.select("a[href^='/url?q=']")

        seen = set()
        for a in anchors:
            raw_link = a.get('href') or ''
            if not raw_link:
                continue
            # normalize (Google results often use /url?q=)
            link = normalize_link(raw_link)
            if not link:
                # try extract q param directly
                link = limpar_link_google(raw_link)
                link = normalize_link(link)
            if not link:
                continue

            # title
            title_elem = a.select_one("div.JheGif") or a.select_one("h3") or a.select_one("div.MBeuO span")
            title = title_elem.get_text(" ", strip=True) if title_elem else a.get_text(" ", strip=True)
            if not title or len(title) < 4:
                title = extract_title_from_url(link)

            if not is_probably_article(title, link):
                continue

            # verify url reachable
            if not url_existente(link):
                continue

            key = (title[:140], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": title, "link": link, "orig_link": raw_link, "fonte": "Google Notícias"})
            if len(resultados) >= limite:
                break

    except Exception as e:
        print("Erro raspar_google_requests:", e)
        traceback.print_exc()

    # print(f"✅ Google (requests) encontrou: {len(resultados)}")
    return resultados

# Fallback selenium functions (mantidos) - serão usados apenas se requests retornar vazio
def raspar_g1(termo):
    res = raspar_g1_requests(termo, limite=12)
    if res:
        return res
    try:
        print("⚠️ G1 via requests não retornou — tentando Selenium fallback...")
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import time

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=options)
        driver.get(f"https://g1.globo.com/busca/?q={quote_plus(termo)}")
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()

        resultados = []
        a_tags = soup.select("a[href*='/noticia/']") or soup.select("article a")
        seen = set()
        for a in a_tags:
            raw_link = a.get('href', '')
            link = normalize_link(raw_link, prefer_domain='https://g1.globo.com')
            if not link:
                continue
            titulo = a.get_text(strip=True) or extract_title_from_url(link)
            if not is_probably_article(titulo, link):
                continue
            if not url_existente(link):
                continue
            key = (titulo[:120], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": titulo, "link": link, "orig_link": raw_link or link, "fonte": "G1"})
            if len(resultados) >= 8:
                break
        return resultados
    except Exception as e:
        print("Fallback Selenium G1 falhou:", e)
        traceback.print_exc()
        return []

def raspar_google_noticias(termo):
    res = raspar_google_requests(termo, limite=12)
    if res:
        return res
    try:
        print("⚠️ Google (requests) não retornou — tentando Selenium fallback...")
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import time

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=options)
        driver.get(f"https://www.google.com/search?q={quote_plus(termo)}&tbm=nws")
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()

        resultados = []
        blocos = soup.select("div.SoaBEf") or soup.select("div.dbsr")
        seen = set()
        for b in blocos:
            a = b.find('a')
            raw_link = a.get('href') if a else ''
            link = normalize_link(raw_link)
            if not link:
                link = limpar_link_google(raw_link)
                link = normalize_link(link)
            if not link:
                continue
            title_elem = b.select_one("h3") or b.select_one("div.MBeuO span")
            title = title_elem.get_text(strip=True) if title_elem else extract_title_from_url(link)
            if not is_probably_article(title, link):
                continue
            if not url_existente(link):
                continue
            key = (title[:140], link)
            if key in seen:
                continue
            seen.add(key)
            resultados.append({"titulo": title, "link": link, "fonte": "Google Notícias"})
            if len(resultados) >= 12:
                break
        return resultados
    except Exception as e:
        print("Fallback Selenium Google falhou:", e)
        traceback.print_exc()
        return []
# app.py - Parte 3/3
# Rotas e integração com banco

def salvar_no_banco(resultados, termo, user_id=None):
    if not resultados:
        return
    conexao = conectar_banco()
    if not conexao:
        print("Não conectou ao banco, pulando salvamento.")
        return
    try:
        with conexao.cursor() as cursor:
            for noticia in resultados:
                sentimento = analisar_sentimento(noticia.get("titulo",""))
                try:
                    cursor.execute("""
                        INSERT INTO noticias (titulo, link, fonte, sentimento, termo)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (noticia.get("titulo",""), noticia.get("link",""), noticia.get("fonte",""), sentimento, termo))
                except Exception as e:
                    # ignora duplicação ou erro de inserção específico
                    print("Erro inserção (continuando):", e)
        conexao.commit()
        conexao.close()
        print("💾 Salvou no banco (ou tentou inserir).")
    except Exception as e:
        print("Erro ao salvar no banco:", e)
        traceback.print_exc()

# ---------------------------
# Rotas: register, login, logout
# ---------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not (nome and email and senha):
            flash("Preencha todos os campos.", "erro")
            return redirect(url_for("register"))

        conexao = conectar_banco()
        if not conexao:
            flash("Erro ao conectar no banco.", "erro")
            return redirect(url_for("register"))

        try:
            with conexao.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
                if cursor.fetchone():
                    flash("Email já cadastrado!", "erro")
                    return redirect(url_for("register"))
                senha_hash = generate_password_hash(senha)
                cursor.execute("""
                    INSERT INTO users (nome, email, senha)
                    VALUES (%s, %s, %s)
                """, (nome, email, senha_hash))
            conexao.commit()
            conexao.close()
            flash("Cadastro realizado com sucesso! Faça login.", "sucesso")
            return redirect(url_for("login"))
        except Exception as e:
            print("Erro ao cadastrar:", e)
            traceback.print_exc()
            flash("Erro ao cadastrar usuário.", "erro")
            return redirect(url_for("register"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not (email and senha):
            flash("Preencha email e senha.", "erro")
            return redirect(url_for("login"))

        conexao = conectar_banco()
        if not conexao:
            flash("Erro ao conectar banco.", "erro")
            return redirect(url_for("login"))

        try:
            with conexao.cursor() as cursor:
                cursor.execute("""
                    SELECT id, nome, senha, tema, resultados_por_pagina, fez_onboarding
                    FROM users
                    WHERE email=%s
                """, (email,))
                user = cursor.fetchone()
            conexao.close()

            if not user:
                flash("Email ou senha incorretos!", "erro")
                return redirect(url_for("login"))

            user_id, user_name, user_hash, tema, resultados_por_pagina, fez_onboarding = user

            if not check_password_hash(user_hash, senha):
                flash("Email ou senha incorretos!", "erro")
                return redirect(url_for("login"))

            session['user_id'] = user_id
            session['user_name'] = user_name
            session['tema'] = tema or 'claro'
            session['resultados'] = resultados_por_pagina or 12

            if fez_onboarding == 0:
                return redirect(url_for("onboarding"))

            flash(f"Bem-vindo(a), {user_name}!", "sucesso")
            return redirect(url_for("index"))

        except Exception as e:
            print("Erro login:", e)
            traceback.print_exc()
            flash("Erro ao fazer login.", "erro")
            return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu da conta.", "sucesso")
    return redirect(url_for("login"))

# ---------------------------
# Onboarding
# ---------------------------
@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conexao = conectar_banco()
    if not conexao:
        flash("Erro ao conectar no banco.", "erro")
        return redirect(url_for("index"))

    if request.method == "POST":
        tema = request.form.get("tema", "claro")
        try:
            resultados = int(request.form.get("resultados", 12))
        except Exception:
            resultados = 12

        try:
            with conexao.cursor() as cursor:
                cursor.execute("""
                    UPDATE users
                    SET fez_onboarding = 1,
                        tema = %s,
                        resultados_por_pagina = %s
                    WHERE id = %s
                """, (tema, resultados, user_id))
            conexao.commit()
            conexao.close()

            session["tema"] = tema
            session["resultados"] = resultados

            flash("Preferências salvas.", "sucesso")
            return redirect(url_for("index"))
        except Exception as e:
            print("Erro ao salvar onboarding:", e)
            traceback.print_exc()
            flash("Erro ao salvar preferências.", "erro")
            return redirect(url_for("onboarding"))

    return render_template("onboarding.html")

# ---------------------------
# Rota principal (protegida)
# ---------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))

    # Verifica se o usuário fez onboarding (caso foi alterado manualmente)
    conexao = conectar_banco()
    if conexao:
        try:
            with conexao.cursor() as cursor:
                cursor.execute("SELECT fez_onboarding FROM users WHERE id=%s", (session["user_id"],))
                status = cursor.fetchone()
            conexao.close()
            if status and status[0] == 0:
                return redirect(url_for("onboarding"))
        except Exception:
            pass

    resultados = []
    sentimentos = {"positivo": 0, "negativo": 0, "neutro": 0}
    termo = ""
    page = int(request.args.get('page', 1) or 1)
    per_page = int(request.args.get('per_page', session.get('resultados', 12) or 12) or 12)
    sources = request.values.getlist('sources') or []
    source_filter = request.args.get('source', '').strip()

    if request.method == "POST":
        termo = (request.form.get("termo") or request.form.get("palavra_chave") or "").strip()
        if termo:
            resultados_g1 = raspar_g1(termo)
            time.sleep(0.25)
            resultados_google = raspar_google_noticias(termo)
            seen_links = set()
            resultados_comb = []
            for r in (resultados_g1 + resultados_google):
                link = r.get("link","")
                if not link:
                    continue
                if link in seen_links:
                    continue
                seen_links.add(link)
                r["sentimento"] = analisar_sentimento(r.get("titulo",""))
                resultados_comb.append(r)
            resultados = resultados_comb

            if os.getenv('SAVE_TO_DB', '0') == '1':
                salvar_no_banco(resultados, termo, user_id=session.get('user_id'))

            for noticia in resultados:
                s = noticia.get("sentimento","neutro")
                sentimentos[s] += 1

    # filtros
    if sources:
        lower_sources = [s.lower() for s in sources]
        resultados = [r for r in resultados if any(ls in (r.get('fonte') or '').lower() for ls in lower_sources)]
    elif source_filter:
        resultados = [r for r in resultados if (r.get('fonte') or '').lower().find(source_filter.lower()) != -1]

    # paginação
    total = len(resultados)
    total_pages = max(1, math.ceil(total / per_page))
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = resultados[start:end]

    return render_template("index.html",
                           resultados=page_items,
                           sentimentos=sentimentos,
                           termo=termo,
                           page=page,
                           per_page=per_page,
                           total=total,
                           total_pages=total_pages,
                           source_filter=source_filter,
                           sources=sources,
                           user_name=session.get('user_name'),
                           tema=session.get('tema'))

# ---------------------------
# API endpoint de busca
# ---------------------------
@app.route('/api/search')
def api_search():
    termo = (request.args.get('termo') or '').strip()
    page = int(request.args.get('page', 1) or 1)
    per_page = int(request.args.get('per_page', 12) or 12)
    source_filter = request.args.get('source', '').strip()

    resultados = []
    if termo:
        resultados_g1 = raspar_g1(termo)
        resultados_google = raspar_google_noticias(termo)
        seen_links = set()
        for r in (resultados_g1 + resultados_google):
            link = r.get('link','')
            if not link:
                continue
            if link in seen_links:
                continue
            seen_links.add(link)
            r['sentimento'] = analisar_sentimento(r.get('titulo',''))
            resultados.append(r)

    if source_filter:
        resultados = [r for r in resultados if (r.get('fonte') or '').lower().find(source_filter.lower()) != -1]

    total = len(resultados)
    total_pages = max(1, math.ceil(total / per_page))
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = resultados[start:end]

    return jsonify({
        'termo': termo,
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
        'results': page_items
    })

# ---------------------------
# Health
# ---------------------------
@app.route('/health')
def health():
    return 'ok'

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    app.run(debug=True)
