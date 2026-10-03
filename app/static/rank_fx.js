// Animaciones de rango (app/strength_standards.py, CSS en style.css):
//  - showRankCelebration(): la celebración de subida de rango, también en
//    mitad de un entreno (la versión de Inicio la pinta el servidor).
//  - Bienvenida breve con tu emblema, una vez al día, que se va sola.
//  - Barra hasta la siguiente división que se rellena desde donde la dejaste.
// Todo respeta prefers-reduced-motion.
(function () {
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function emblemSrc(rank) {
        return '/static/ranks/' + rank.file + '.svg';
    }

    window.showRankCelebration = function (rank) {
        if (!rank || document.getElementById('rankCelebration')) return;
        const el = document.createElement('div');
        el.className = 'rank-celebration tier-' + rank.key;
        el.id = 'rankCelebration';
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-modal', 'true');
        let sparks = '';
        for (let i = 0; i < 14; i++) {
            sparks += '<i class="rank-spark" style="--a: ' + (i * 360 / 14) + 'deg; --d: ' + (0.15 + (i % 4) * 0.08) + 's"></i>';
        }
        el.innerHTML =
            '<div class="rank-celebration-card">' +
            '<div class="rank-celebration-emblem"><span class="rank-celebration-rays" aria-hidden="true"></span>' + sparks +
            '<img class="rank-emblem" src="' + emblemSrc(rank) + '" width="190" height="190" alt=""></div>' +
            '<small>¡Has subido de rango!</small><strong></strong>' +
            '<p>Acabas de conseguirlo con este récord. Sigue así.</p>' +
            '<div class="rank-celebration-actions"><a class="btn" href="/rango">Ver mi rango</a>' +
            '<button type="button" class="btn-outline">Seguir entrenando</button></div></div>';
        el.querySelector('strong').textContent = rank.label;
        function close() {
            el.classList.add('is-closing');
            setTimeout(function () { el.remove(); }, 250);
        }
        el.querySelector('button').addEventListener('click', close);
        el.addEventListener('click', function (e) { if (e.target === el) close(); });
        document.body.appendChild(el);
    };

    // Bienvenida: una vez al día, ~1,2 s, se quita sola y con un toque.
    function splash() {
        const data = document.getElementById('rankSplashData');
        if (!data || reduced || document.getElementById('rankCelebration')) return;
        const today = new Date().toISOString().slice(0, 10);
        try {
            if (localStorage.getItem('gyre-rank-splash') === today) return;
            localStorage.setItem('gyre-rank-splash', today);
        } catch (e) { return; }
        const rank = JSON.parse(data.textContent);
        const el = document.createElement('div');
        el.className = 'rank-splash tier-' + rank.key;
        el.innerHTML = '<img class="rank-emblem" src="' + emblemSrc(rank) + '" width="170" height="170" alt="">' +
            '<strong></strong>';
        el.querySelector('strong').textContent = rank.label;
        function close() {
            if (el.classList.contains('is-closing')) return;
            el.classList.add('is-closing');
            setTimeout(function () { el.remove(); }, 300);
        }
        el.addEventListener('click', close);
        document.body.appendChild(el);
        setTimeout(close, 1250);
    }

    // Barra de la pestaña Rango: arranca donde la dejaste la última vez.
    function animateBar() {
        const bar = document.querySelector('.rank-hero-bar i');
        if (!bar) return;
        const target = parseFloat(bar.dataset.pct || '0');
        const label = bar.dataset.label || '';
        let from = 0;
        try {
            const prev = JSON.parse(localStorage.getItem('gyre-rank-bar') || 'null');
            if (prev && prev.label === label) from = prev.pct;
            localStorage.setItem('gyre-rank-bar', JSON.stringify({ label: label, pct: target }));
        } catch (e) {}
        if (reduced) { bar.style.width = target + '%'; return; }
        bar.style.transition = 'none';
        bar.style.width = from + '%';
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                bar.style.transition = 'width 1.2s cubic-bezier(0.2, 0.9, 0.3, 1)';
                bar.style.width = target + '%';
            });
        });
    }

    // Vitrina: centrada en tu rango actual (sin mover la página).
    function centerShowcase() {
        const box = document.querySelector('.rank-showcase');
        const current = box && box.querySelector('.is-current');
        if (!current) return;
        box.scrollLeft = current.offsetLeft - box.clientWidth / 2 + current.clientWidth / 2;
    }

    document.addEventListener('DOMContentLoaded', function () {
        splash();
        animateBar();
        centerShowcase();
    });
})();
