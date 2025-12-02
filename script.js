// Minimal JS to improve UX: show loader on submit and clear form
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('searchForm');
  var loader = document.getElementById('loader');
  var limpar = document.getElementById('limparBtn');
  var buscar = document.getElementById('buscarBtn');
  var termo = document.getElementById('termo');

  if (form) {
    form.addEventListener('submit', function () {
      if (loader) {
        loader.hidden = false;
        loader.setAttribute('aria-hidden', 'false');
      }
      if (buscar) buscar.setAttribute('aria-disabled', 'true');
    });
  }

  if (limpar) {
    limpar.addEventListener('click', function () {
      if (termo) termo.value = '';
      // hide loader if visible
      if (loader) {
        loader.hidden = true;
        loader.setAttribute('aria-hidden', 'true');
      }
      // submit empty form to clear server-side results OR you can just remove elements client-side
      // here we'll simply focus the input
      if (termo) termo.focus();
    });
  }
  
    // Load more via API
    var loadMoreBtn = document.getElementById('loadMore');
    if (loadMoreBtn) {
      loadMoreBtn.addEventListener('click', function () {
        var nextPage = parseInt(loadMoreBtn.getAttribute('data-next') || '2');
        var perPage = loadMoreBtn.getAttribute('data-perpage') || '12';
        var source = (document.querySelector('input[name="source"]')||{}).value || '';
        var termoVal = (document.getElementById('termo')||{}).value || '';
        if (!termoVal) return;
        loadMoreBtn.disabled = true;
        fetch(`/api/search?termo=${encodeURIComponent(termoVal)}&page=${nextPage}&per_page=${perPage}&source=${encodeURIComponent(source)}`)
          .then(function (res) { return res.json(); })
          .then(function (data) {
            appendArticles(data.results || []);
            var newNext = nextPage + 1;
            if (newNext > (data.total_pages||1)) {
              loadMoreBtn.style.display = 'none';
            } else {
              loadMoreBtn.setAttribute('data-next', String(newNext));
              loadMoreBtn.disabled = false;
            }
          }).catch(function (err) {
            console.error(err);
            loadMoreBtn.disabled = false;
          });
      });
    }

    function appendArticles(items) {
      var container = document.querySelector('.noticias');
      if (!container) {
        container = document.createElement('section');
        container.className = 'noticias';
        var parent = document.querySelector('.container') || document.body;
        parent.appendChild(container);
      }
      items.forEach(function (it) {
        var art = document.createElement('article');
  art.className = 'noticia ' + (it.sentimento || '');
        var h = document.createElement('h3'); h.textContent = it.titulo || it.title || '';
        var p = document.createElement('p'); p.className = 'meta';
        var badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = it.fonte || '';
        p.appendChild(badge);
        if (it.sentimento) {
          var sb = document.createElement('span'); sb.className = 'badge sentimento ' + it.sentimento; sb.textContent = it.sentimento.charAt(0).toUpperCase()+it.sentimento.slice(1);
          p.appendChild(sb);
        }
  var a = document.createElement('a'); a.href = it.orig_link || it.link || '#'; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = 'Ler notícia completa';
        art.appendChild(h); art.appendChild(p); art.appendChild(a);
        container.appendChild(art);
      });
    }
});
