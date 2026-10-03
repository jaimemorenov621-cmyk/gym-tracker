// Aviso de XP tipo videojuego (Inicio): "+N XP" contando hacia arriba, el
// desglose, la barra de nivel rellenándose y "¡NIVEL N!" si subes. Datos en
// #xpFxData (xp_fx_data en app/routes.py). Se va solo; un toque lo cierra.
// Espera a que terminen la celebración y la bienvenida de rango (rank_fx.js).
(function () {
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function whenClear(cb) {
        if (document.getElementById('rankCelebration') || document.querySelector('.rank-splash')) {
            setTimeout(function () { whenClear(cb); }, 300);
        } else {
            cb();
        }
    }

    function show(d) {
        const crosses = d.to.level > d.from.level;
        const el = document.createElement('div');
        el.className = 'xp-pop';
        el.setAttribute('role', 'status');
        el.innerHTML =
            '<div class="xp-pop-card">' +
            '<div class="xp-pop-head"><span class="xp-pop-reason"></span><strong class="xp-pop-gain"></strong></div>' +
            '<div class="xp-pop-parts"></div>' +
            '<div class="xp-pop-level"><span class="xp-pop-badge"><small>NV</small><b></b></span>' +
            '<span class="xp-pop-track"><span class="xp-pop-bar"><i></i></span><span class="xp-pop-next"></span></span></div>' +
            '<div class="xp-pop-up" hidden></div></div>';
        const gainEl = el.querySelector('.xp-pop-gain');
        const badge = el.querySelector('.xp-pop-badge b');
        const bar = el.querySelector('.xp-pop-bar i');
        const up = el.querySelector('.xp-pop-up');
        el.querySelector('.xp-pop-reason').textContent = d.reason || 'Subida de nivel';
        el.querySelector('.xp-pop-next').textContent = 'Faltan ' + d.to.to_next.toLocaleString('es-ES') + ' XP para el nivel ' + (d.to.level + 1);
        const parts = el.querySelector('.xp-pop-parts');
        (d.parts || []).forEach(function (p, i) {
            const chip = document.createElement('span');
            chip.style.animationDelay = (0.35 + i * 0.12) + 's';
            chip.textContent = p[0] + ' ';
            const b = document.createElement('b');
            b.textContent = '+' + p[1];
            chip.appendChild(b);
            parts.appendChild(chip);
        });
        if (!d.parts || !d.parts.length) parts.remove();

        function setGain(n) { gainEl.innerHTML = '+' + n + '<small>XP</small>'; }
        function levelUp() {
            badge.textContent = d.to.level;
            el.classList.add('is-levelup');
            if (d.level_up) {
                up.textContent = '¡NIVEL ' + d.to.level + '!';
                up.hidden = false;
            }
        }

        let closed = false;
        function close() {
            if (closed) return;
            closed = true;
            el.classList.add('is-closing');
            setTimeout(function () { el.remove(); }, 300);
        }
        el.addEventListener('click', close);
        if (!d.gain) gainEl.remove();

        if (reduced) {
            if (d.gain) setGain(d.gain);
            badge.textContent = d.from.level;
            bar.style.width = d.to.pct + '%';
            if (crosses) levelUp();
            document.body.appendChild(el);
            setTimeout(close, crosses && d.level_up ? 4500 : 3500);
            return;
        }

        badge.textContent = d.from.level;
        bar.style.width = d.from.pct + '%';
        if (d.gain) setGain(0);
        document.body.appendChild(el);

        // +N contando hacia arriba (ease-out)
        if (d.gain) {
            const t0 = performance.now() + 250, dur = 900;
            (function tick(now) {
                const t = Math.min(1, Math.max(0, (now - t0) / dur));
                setGain(Math.round(d.gain * (1 - Math.pow(1 - t, 3))));
                if (t < 1) requestAnimationFrame(tick);
                else gainEl.classList.add('is-done');
            })(performance.now());
        }

        // Barra: hasta el final si subes de nivel, y luego desde 0 en el nuevo.
        setTimeout(function () {
            bar.style.transition = 'width 0.9s cubic-bezier(0.3, 0.8, 0.3, 1)';
            bar.style.width = (crosses ? 100 : d.to.pct) + '%';
        }, 350);
        if (crosses) {
            setTimeout(function () {
                levelUp();
                bar.style.transition = 'none';
                bar.style.width = '0%';
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        bar.style.transition = 'width 0.7s cubic-bezier(0.3, 0.8, 0.3, 1)';
                        bar.style.width = d.to.pct + '%';
                    });
                });
            }, 1300);
        }
        setTimeout(close, crosses && d.level_up ? 4600 : 3200);
    }

    document.addEventListener('DOMContentLoaded', function () {
        const data = document.getElementById('xpFxData');
        if (!data) return;
        const d = JSON.parse(data.textContent);
        // Un poco de margen para que se vea después del confeti / la carga.
        setTimeout(function () { whenClear(function () { show(d); }); }, 400);
    });
})();
