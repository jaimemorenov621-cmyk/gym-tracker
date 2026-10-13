// Tarjetas para compartir en historias (Instagram, WhatsApp...): récord
// (GET /set/<id>/share), rango (GET /share/rank/<global|lift>) y logro
// (GET /share/achievement/<code>); d.kind dice cuál. Se dibujan en un
// <canvas> en el propio navegador (sin servidor de imágenes) y se comparten
// con la Web Share API
// (archivo PNG + texto con enlace ?ref=compartir); si el navegador no puede
// compartir archivos (escritorio), se descarga.

(function () {
    const W = 1080, H = 1920;
    const FONT = '"Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
    let currentBlob = null, currentData = null, currentUrl = null, toastTimer = null;
    // Diseño por defecto (siempre disponible); los demás se desbloquean por
    // nivel y llegan en data.designs (app/perks.py).
    const CLASSIC = {
        key: 'clasico', bg: ['#120c2c', '#251663'], glows: ['rgba(124, 77, 255, 0.55)', 'rgba(34, 201, 140, 0.25)'],
        kicker: '#c9b8ff', metric: ['#b69cff', '#7fd8ff', '#5cf0b4'], link: '#b69cff'
    };

    function chosenDesign(d) {
        const designs = (d.designs && d.designs.length) ? d.designs : [CLASSIC];
        let key = null;
        try { key = localStorage.getItem('gyre-share-design'); } catch (e) {}
        return designs.find(function (x) { return x.key === key; }) || designs[0];
    }

    function toast(message) {
        if (window.showPickerErrorToast) return window.showPickerErrorToast(message);
        alert(message);
    }

    function loadLogo() {
        return new Promise(function (resolve) {
            const img = new Image();
            img.onload = function () { resolve(img); };
            img.onerror = function () { resolve(null); };
            img.src = '/static/icons/logo-mark.png';
        });
    }

    function loadImage(src) {
        return new Promise(function (resolve) {
            const img = new Image();
            img.onload = function () { resolve(img); };
            img.onerror = function () { resolve(null); };
            img.src = src;
        });
    }

    function roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }

    function wrapLines(ctx, text, maxWidth, maxLines) {
        const words = text.split(/\s+/);
        const lines = [];
        let line = '';
        words.forEach(function (word) {
            const test = line ? line + ' ' + word : word;
            if (ctx.measureText(test).width > maxWidth && line) {
                lines.push(line);
                line = word;
            } else {
                line = test;
            }
        });
        if (line) lines.push(line);
        if (lines.length > maxLines) {
            // Lo que no cabe se junta en la última línea y se recorta por
            // caracteres (no por palabras: podía quedar una línea solo con "…").
            const kept = lines.slice(0, maxLines - 1);
            let last = lines.slice(maxLines - 1).join(' ');
            while (last.length > 1 && ctx.measureText(last + '…').width > maxWidth) last = last.slice(0, -1);
            kept.push(last.trim() + '…');
            return kept;
        }
        return lines;
    }

    // Nombre del ejercicio: baja el tamaño (92 → 64px) antes de recortar.
    function fitName(ctx, text) {
        let size = 92, lines;
        for (; size >= 64; size -= 6) {
            ctx.font = '800 ' + size + 'px ' + FONT;
            lines = wrapLines(ctx, text, 920, 2);
            if (!lines[lines.length - 1].endsWith('…')) break;
        }
        size = Math.max(size, 64);
        ctx.font = '800 ' + size + 'px ' + FONT;
        return { size: size, lines: wrapLines(ctx, text, 920, 2) };
    }

    function es(num) { return GYRE_NUM_LOCALE === 'en-US' ? String(num) : String(num).replace('.', ','); }

    function setSpacing(ctx, px) {
        if ('letterSpacing' in ctx) ctx.letterSpacing = px + 'px';
    }

    function drawRecord(ctx, d, design) {
        // Centrado vertical del bloque central: sin la píldora de mejora y
        // con el nombre en una sola línea queda más bajo, así no deja un
        // hueco grande encima de la fecha.
        const name = fitName(ctx, d.exercise);
        const hasImprovement = d.improvement && d.improvement > 0;
        const off = (hasImprovement ? 0 : 70) + (name.lines.length === 1 ? 50 : 0);
        ctx.translate(0, off);

        // Medalla + etiqueta.
        ctx.font = '210px ' + FONT;
        ctx.fillText(d.is_pr ? '🏅' : '💪', W / 2, 610);
        ctx.font = '800 44px ' + FONT;
        setSpacing(ctx, 8);
        ctx.fillStyle = design.kicker;
        ctx.fillText(d.is_pr ? T('NUEVO RÉCORD PERSONAL') : T('MI ENTRENO DE HOY'), W / 2, 730);
        setSpacing(ctx, 0);

        // Ejercicio (hasta 2 líneas).
        ctx.font = '800 ' + name.size + 'px ' + FONT;
        ctx.fillStyle = '#ffffff';
        let y = 870;
        name.lines.forEach(function (line) { ctx.fillText(line, W / 2, y); y += Math.round(name.size * 1.18); });

        // Cifra principal con degradado.
        const main = es(d.weight) + ' kg × ' + d.reps;
        let size = 176;
        ctx.font = '800 ' + size + 'px ' + FONT;
        while (ctx.measureText(main).width > 960 && size > 100) {
            size -= 8;
            ctx.font = '800 ' + size + 'px ' + FONT;
        }
        y += 120;
        const mw = ctx.measureText(main).width;
        const grad = ctx.createLinearGradient((W - mw) / 2, 0, (W + mw) / 2, 0);
        grad.addColorStop(0, design.metric[0]);
        grad.addColorStop(0.55, design.metric[1]);
        grad.addColorStop(1, design.metric[2]);
        ctx.fillStyle = grad;
        ctx.fillText(main, W / 2, y);

        ctx.font = '600 54px ' + FONT;
        ctx.fillStyle = 'rgba(255, 255, 255, 0.82)';
        y += 100;
        ctx.fillText(T('1RM estimado · {kg} kg').replace('{kg}', d.e1rm), W / 2, y);

        // Mejora sobre la mejor marca anterior.
        if (hasImprovement) {
            const txt = '▲ ' + T('+{kg} kg sobre tu mejor marca').replace('{kg}', es(d.improvement));
            ctx.font = '700 44px ' + FONT;
            const tw = ctx.measureText(txt).width;
            const pw = tw + 80, ph = 92, px = (W - pw) / 2, py = y + 70;
            roundRect(ctx, px, py, pw, ph, 46);
            ctx.fillStyle = 'rgba(34, 201, 140, 0.18)';
            ctx.fill();
            ctx.lineWidth = 3;
            ctx.strokeStyle = 'rgba(92, 240, 180, 0.7)';
            ctx.stroke();
            ctx.fillStyle = '#5cf0b4';
            ctx.fillText(txt, W / 2, py + 61);
        }

        ctx.translate(0, -off);
    }

    // Texto en una línea que se encoge hasta caber (mínimo `min` px).
    function fitText(ctx, text, weight, size, maxWidth, min) {
        ctx.font = weight + ' ' + size + 'px ' + FONT;
        while (ctx.measureText(text).width > maxWidth && size > min) {
            size -= 6;
            ctx.font = weight + ' ' + size + 'px ' + FONT;
        }
        return size;
    }

    function gradientText(ctx, text, y, design) {
        const mw = ctx.measureText(text).width;
        const grad = ctx.createLinearGradient((W - mw) / 2, 0, (W + mw) / 2, 0);
        grad.addColorStop(0, design.metric[0]);
        grad.addColorStop(0.55, design.metric[1]);
        grad.addColorStop(1, design.metric[2]);
        ctx.fillStyle = grad;
        ctx.fillText(text, W / 2, y);
    }

    function kicker(ctx, text, y, design) {
        ctx.font = '800 44px ' + FONT;
        setSpacing(ctx, 8);
        ctx.fillStyle = design.kicker;
        ctx.fillText(text, W / 2, y);
        setSpacing(ctx, 0);
    }

    // Rango: el emblema grande, el rango y de qué es (global o un básico).
    async function drawRank(ctx, d, design) {
        const emblem = d.emblem ? await loadImage('/static/ranks/' + d.emblem + '-512.webp') : null;
        if (emblem) ctx.drawImage(emblem, (W - 600) / 2, 400, 600, 600);
        kicker(ctx, T('MI RANGO DE FUERZA'), 1090, design);
        fitText(ctx, d.label, '800', 160, 900, 96);
        gradientText(ctx, d.label, 1270, design);
        fitText(ctx, d.subtitle, '800', 70, 940, 44);
        ctx.fillStyle = '#ffffff';
        ctx.fillText(d.subtitle, W / 2, 1385);
        if (d.detail) {
            fitText(ctx, d.detail, '600', 48, 940, 32);
            ctx.fillStyle = 'rgba(255, 255, 255, 0.78)';
            ctx.fillText(d.detail, W / 2, 1470);
        }
    }

    // Logro: su emoji, el título y la descripción.
    function drawAchievement(ctx, d, design) {
        ctx.font = '260px ' + FONT;
        ctx.fillStyle = '#ffffff';
        ctx.fillText(d.emoji, W / 2, 780);
        kicker(ctx, T('LOGRO DESBLOQUEADO'), 920, design);
        const name = fitName(ctx, d.title);
        ctx.fillStyle = '#ffffff';
        let y = 1070;
        name.lines.forEach(function (line) { ctx.fillText(line, W / 2, y); y += Math.round(name.size * 1.18); });
        ctx.font = '500 50px ' + FONT;
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        y += 40;
        wrapLines(ctx, d.desc || '', 900, 3).forEach(function (line) { ctx.fillText(line, W / 2, y); y += 68; });
        if (d.category) {
            ctx.font = '700 40px ' + FONT;
            const tw = ctx.measureText(d.category).width;
            const pw = tw + 72, ph = 80, px = (W - pw) / 2, py = y + 30;
            roundRect(ctx, px, py, pw, ph, 40);
            ctx.fillStyle = 'rgba(255, 255, 255, 0.1)';
            ctx.fill();
            ctx.fillStyle = design.kicker;
            ctx.fillText(d.category, W / 2, py + 54);
        }
    }

    async function drawCard(d, design) {
        design = design || CLASSIC;
        const canvas = document.createElement('canvas');
        canvas.width = W;
        canvas.height = H;
        const ctx = canvas.getContext('2d');
        if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (e) {} }
        const logo = await loadLogo();

        // Fondo: mismo lenguaje que la landing (oscuro + brillos morado/verde).
        const bg = ctx.createLinearGradient(0, 0, 0, H);
        bg.addColorStop(0, design.bg[0]);
        bg.addColorStop(1, design.bg[1]);
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, W, H);
        [[880, 260, 760, design.glows[0]], [140, 1700, 700, design.glows[1]]].forEach(function (g) {
            const rg = ctx.createRadialGradient(g[0], g[1], 0, g[0], g[1], g[2]);
            rg.addColorStop(0, g[3]);
            rg.addColorStop(1, 'rgba(0, 0, 0, 0)');
            ctx.fillStyle = rg;
            ctx.fillRect(0, 0, W, H);
        });

        ctx.textAlign = 'center';
        ctx.textBaseline = 'alphabetic';

        // Marca arriba: logo + "Gyre".
        ctx.font = '800 68px ' + FONT;
        const brandW = ctx.measureText('Gyre').width;
        const logoSize = logo ? 92 : 0, gap = logo ? 22 : 0;
        const startX = (W - (logoSize + gap + brandW)) / 2;
        if (logo) ctx.drawImage(logo, startX, 150, logoSize, logoSize);
        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'left';
        ctx.fillText('Gyre', startX + logoSize + gap, 218);
        ctx.textAlign = 'center';

        // Insignia de nivel (y rango con su emblema), ventaja a partir del nivel 10.
        if (d.badge) {
            const emblem = d.rank_key ? await loadImage('/static/ranks/' + d.rank_key + '-512.webp') : null;
            const es_ = emblem ? 84 : 0;
            ctx.font = '800 38px ' + FONT;
            setSpacing(ctx, 4);
            const tw = ctx.measureText(d.badge).width;
            const bw = tw + 64 + (emblem ? es_ - 10 : 0);
            const bx = (W - bw) / 2;
            roundRect(ctx, bx, 282, bw, 70, 35);
            ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
            ctx.fill();
            ctx.lineWidth = 2;
            ctx.strokeStyle = design.kicker;
            ctx.stroke();
            if (emblem) ctx.drawImage(emblem, bx + 6, 275, es_, es_);
            ctx.fillStyle = design.kicker;
            ctx.textAlign = 'left';
            ctx.fillText(d.badge, bx + 32 + (emblem ? es_ - 10 : 0), 330);
            ctx.textAlign = 'center';
            setSpacing(ctx, 0);
        }

        if (d.kind === 'rank') await drawRank(ctx, d, design);
        else if (d.kind === 'achievement') drawAchievement(ctx, d, design);
        else drawRecord(ctx, d, design);

        // Fecha y pie con el enlace.
        ctx.font = '600 42px ' + FONT;
        ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
        ctx.fillText(d.date, W / 2, 1610);
        ctx.fillStyle = 'rgba(255, 255, 255, 0.14)';
        ctx.fillRect(W / 2 - 220, 1665, 440, 3);
        ctx.font = '700 44px ' + FONT;
        ctx.fillStyle = '#ffffff';
        ctx.fillText(T('Registra tus entrenos gratis con Gyre'), W / 2, 1755);
        ctx.font = '600 38px ' + FONT;
        ctx.fillStyle = design.link;
        ctx.fillText(new URL(d.share_url).host, W / 2, 1818);

        return new Promise(function (resolve) { canvas.toBlob(resolve, 'image/png'); });
    }

    function ensureSheet() {
        let sheet = document.getElementById('shareCardSheet');
        if (sheet) return sheet;
        const backdrop = document.createElement('div');
        backdrop.className = 'sheet-backdrop';
        backdrop.id = 'shareCardBackdrop';
        backdrop.addEventListener('click', closeShareCard);
        sheet = document.createElement('div');
        sheet.className = 'bottom-sheet share-card-sheet';
        sheet.id = 'shareCardSheet';
        sheet.setAttribute('role', 'dialog');
        sheet.setAttribute('aria-modal', 'true');
        sheet.innerHTML =
            '<div class="bottom-sheet-grabber" aria-hidden="true"></div>' +
            '<div class="bottom-sheet-header">' +
            '<h3 class="bottom-sheet-title share-card-title">' + T('Comparte tu récord') + '</h3>' +
            '<button type="button" class="sheet-close-btn" aria-label="' + T('Cerrar') + '">' +
            '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
            '</button></div>' +
            '<div class="share-card-preview"><span class="share-card-loading">' + T('Preparando tarjeta…') + '</span></div>' +
            '<div class="share-designs" role="radiogroup" aria-label="' + T('Diseño de la tarjeta') + '"></div>' +
            '<div class="share-card-actions">' +
            '<button type="button" class="btn share-card-share" disabled>' + T('Compartir') + '</button>' +
            '<button type="button" class="btn-outline share-card-download" disabled>' + T('Descargar') + '</button>' +
            '</div>' +
            '<p class="share-card-hint">' + T('Perfecta para historias de Instagram o el estado de WhatsApp.') + '</p>';
        sheet.querySelector('.sheet-close-btn').addEventListener('click', closeShareCard);
        sheet.querySelector('.share-card-share').addEventListener('click', shareCurrent);
        sheet.querySelector('.share-card-download').addEventListener('click', downloadCurrent);
        document.body.appendChild(backdrop);
        document.body.appendChild(sheet);
        return sheet;
    }

    async function redraw(sheet, design) {
        const preview = sheet.querySelector('.share-card-preview');
        currentBlob = await drawCard(currentData, design);
        if (currentUrl) URL.revokeObjectURL(currentUrl);
        currentUrl = URL.createObjectURL(currentBlob);
        const img = document.createElement('img');
        img.src = currentUrl;
        img.alt = cardAlt(currentData);
        preview.innerHTML = '';
        preview.appendChild(img);
        sheet.querySelectorAll('.share-design').forEach(function (b) {
            const on = b.dataset.key === design.key;
            b.classList.toggle('selected', on);
            b.setAttribute('aria-checked', on ? 'true' : 'false');
        });
    }

    function renderDesignChips(sheet, data) {
        const box = sheet.querySelector('.share-designs');
        box.innerHTML = '';
        const designs = data.designs || [];
        box.hidden = designs.length < 2;
        designs.forEach(function (design) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'share-design';
            b.dataset.key = design.key;
            b.setAttribute('role', 'radio');
            b.textContent = design.name;
            b.addEventListener('click', function () {
                try { localStorage.setItem('gyre-share-design', design.key); } catch (e) {}
                redraw(sheet, design);
            });
            box.appendChild(b);
        });
    }

    function closeShareCard() {
        const sheet = document.getElementById('shareCardSheet');
        if (!sheet) return;
        sheet.classList.remove('open');
        document.getElementById('shareCardBackdrop').classList.remove('open');
        document.body.style.overflow = '';
    }

    const TITLES = {record: 'Comparte tu récord', rank: 'Comparte tu rango', achievement: 'Comparte tu logro'};

    function cardAlt(d) {
        if (d.kind === 'rank') return T('Tarjeta de rango: {name}').replace('{name}', d.label + ' · ' + d.subtitle);
        if (d.kind === 'achievement') return T('Tarjeta del logro {name}').replace('{name}', d.title);
        return T('Tarjeta de récord de {name}').replace('{name}', d.exercise);
    }

    // openShareCard(idDeSerie) para un récord, u openShareCard({kind:
    // 'rank'|'achievement', key}) para un rango o un logro.
    async function openShareCard(arg) {
        hidePrShareToast();
        const kind = (arg && typeof arg === 'object') ? arg.kind : 'record';
        const url = kind === 'record' ? '/set/' + arg + '/share' : '/share/' + kind + '/' + encodeURIComponent(arg.key);
        const sheet = ensureSheet();
        sheet.querySelector('.share-card-title').textContent = T(TITLES[kind] || TITLES.record);
        const preview = sheet.querySelector('.share-card-preview');
        preview.innerHTML = '<span class="share-card-loading">' + T('Preparando tarjeta…') + '</span>';
        sheet.querySelectorAll('.share-card-actions button').forEach(function (b) { b.disabled = true; });
        sheet.classList.add('open');
        document.getElementById('shareCardBackdrop').classList.add('open');
        document.body.style.overflow = 'hidden';

        try {
            const res = await fetch(url);
            const data = await res.json();
            if (!data.ok) throw new Error(data.error || T('No se pudo preparar la tarjeta.'));
            currentData = data;
            renderDesignChips(sheet, data);
            await redraw(sheet, chosenDesign(data));
            sheet.querySelectorAll('.share-card-actions button').forEach(function (b) { b.disabled = false; });
        } catch (e) {
            closeShareCard();
            toast(e.message || T('No se pudo preparar la tarjeta.'));
        }
    }

    function shareText(d) {
        if (d.kind === 'rank' && d.global) {
            return T('🎖️ Mi rango de fuerza: {rank}. Lo apunto todo con Gyre 👉 {url}')
                .replace('{rank}', d.label).replace('{url}', d.share_url);
        }
        if (d.kind === 'rank') {
            return T('🎖️ Mi rango de fuerza en {name}: {rank}. Lo apunto todo con Gyre 👉 {url}')
                .replace('{name}', d.subtitle).replace('{rank}', d.label).replace('{url}', d.share_url);
        }
        if (d.kind === 'achievement') {
            return T('{emoji} Logro desbloqueado: {name}. Lo apunto todo con Gyre 👉 {url}')
                .replace('{emoji}', d.emoji).replace('{name}', d.title).replace('{url}', d.share_url);
        }
        return T('🏅 Nuevo récord en {name}: {kg} kg × {reps} (1RM est. {e1rm} kg). Lo apunto todo con Gyre 👉 {url}')
            .replace('{name}', d.exercise).replace('{kg}', es(d.weight)).replace('{reps}', d.reps)
            .replace('{e1rm}', d.e1rm).replace('{url}', d.share_url);
    }

    async function shareCurrent() {
        if (!currentBlob) return;
        const file = new File([currentBlob], fileName(currentData), { type: 'image/png' });
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
            try {
                await navigator.share({ files: [file], text: shareText(currentData) });
            } catch (e) {
                if (e.name !== 'AbortError') downloadCurrent();
            }
        } else {
            downloadCurrent();
        }
    }

    function fileName(d) {
        return 'gyre-' + ({rank: 'rango', achievement: 'logro'}[d && d.kind] || 'record') + '.png';
    }

    function downloadCurrent() {
        if (!currentUrl) return;
        const a = document.createElement('a');
        a.href = currentUrl;
        a.download = fileName(currentData);
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    // Aviso tras batir un récord en el entreno: "🏅 ¡Nuevo récord! Compartir".
    function showPrShareToast(setId, exercise) {
        hidePrShareToast();
        const el = document.createElement('div');
        el.className = 'pr-share-toast';
        el.id = 'prShareToast';
        el.innerHTML = '<span class="pr-share-toast-medal">🏅</span>' +
            '<span class="pr-share-toast-text"><strong>' + T('¡Nuevo récord!') + '</strong><small></small></span>' +
            '<button type="button" class="pr-share-toast-btn">' + T('Compartir') + '</button>';
        el.querySelector('small').textContent = exercise || '';
        el.querySelector('button').addEventListener('click', function () { openShareCard(setId); });
        document.body.appendChild(el);
        void el.offsetWidth;
        el.classList.add('visible');
        toastTimer = setTimeout(hidePrShareToast, 8000);
    }

    function hidePrShareToast() {
        clearTimeout(toastTimer);
        const el = document.getElementById('prShareToast');
        if (!el) return;
        el.classList.remove('visible');
        setTimeout(function () { el.remove(); }, 250);
    }

    // La medalla 🏅 de cualquier serie también abre la tarjeta.
    document.addEventListener('click', function (e) {
        const badge = e.target.closest('.pr-badge');
        if (!badge) return;
        const row = badge.closest('tr[id^="row-"]');
        if (row) openShareCard(row.id.slice(4));
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeShareCard();
    });

    window.openShareCard = openShareCard;
    window.showPrShareToast = showPrShareToast;
})();
