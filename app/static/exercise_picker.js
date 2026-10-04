let searchTimeout;
let lastSearchResults = [];
let lastSearchQuery = '';
let pickerErrorTimeout;
let pickerReplaceUrl = null;
let pickerReplaceExtra = null;
const MUSCLE_OPTIONS = [
    ['shoulders', T('Hombros')],
    ['neck', T('Cuello')],
    ['chest', T('Pecho')],
    ['abdominals', T('Abdomen')],
    ['biceps', T('Bíceps')],
    ['triceps', T('Tríceps')],
    ['forearms', T('Antebrazos')],
    ['quadriceps', T('Cuádriceps')],
    ['adductors', T('Aductores')],
    ['abductors', T('Abductores')],
    ['glutes', T('Glúteos')],
    ['hamstrings', T('Isquiotibiales')],
    ['lats', T('Dorsales')],
    ['middle back', T('Espalda media')],
    ['lower back', T('Espalda baja')],
    ['traps', T('Trapecios')],
    ['calves', T('Pantorrillas')],
];

// Músculos del catálogo (en inglés, separados por comas) en el idioma de la app.
const MUSCLE_LABEL = Object.fromEntries(MUSCLE_OPTIONS);
function muscleLabels(text) {
    return String(text).split(',').map(m => MUSCLE_LABEL[m.trim()] || m.trim()).filter(Boolean).join(', ');
}

const STAR_ICON_SVG = '<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>';

function resultRowHTML(ex) {
    return '<div class="exercise-result-row" onclick="selectExercise(\'' + ex.name.replace(/'/g, "\\'") + '\')">' +
        (ex.image ? '<img class="exercise-result-thumb" src="' + ex.image + '">' : '<div class="exercise-result-thumb-fallback"><img src="/static/icons/logo-mark.png" alt="" style="max-width:26px; max-height:26px; object-fit:contain;"></div>') +
        '<div><div class="exercise-result-name">' + ex.name + '</div>' +
        (ex.muscles ? '<div class="exercise-result-muscles">' + muscleLabels(ex.muscles) + '</div>' : '') +
        '</div>' +
        (ex.id ? '<button type="button" class="exercise-favorite-star' + (ex.is_favorite ? ' is-favorite' : '') +
            '" onclick="toggleFavorite(event, \'' + ex.id + '\')" aria-label="' + T('Marcar como favorito') + '">' + STAR_ICON_SVG + '</button>' : '') +
        '</div>';
}

function toggleFavorite(event, id) {
    event.stopPropagation();
    const btn = event.currentTarget; // capturar ya -- tras el primer microtask event.currentTarget pasa a null
    fetch('/api/exercises/' + encodeURIComponent(id) + '/favorite', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (!data.ok) return;
            btn.classList.toggle('is-favorite', data.favorite);
        });
}

function searchExercises(query) {
    clearTimeout(searchTimeout);
    if (query.trim().length < 2) {
        resetExercisePickerResults();
        return;
    }
    searchTimeout = setTimeout(() => {
        fetch('/api/exercises/search?q=' + encodeURIComponent(query))
            .then(r => r.json())
            .then(results => {
                lastSearchResults = results;
                lastSearchQuery = query;
                renderResults();
            });
    }, 250);
}

function renderResults() {
    const box = document.getElementById('exercisePickerResults');
    let html = lastSearchResults.length
        ? lastSearchResults.map(resultRowHTML).join('')
        : '<div class="exercise-picker-hint">' + T('Sin resultados en el catálogo.') + '</div>';
    html += '<div class="exercise-picker-footer">' +
        '<button type="button" onclick="startCreateExercise()" class="btn-outline" style="width:100%;">' + T('+ Crear ejercicio nuevo') + '</button>' +
        '</div>';
    box.innerHTML = html;
}

function startCreateExercise() {
    const box = document.getElementById('exercisePickerResults');
    if (lastSearchResults.length) {
        box.innerHTML = '<div class="exercise-picker-hint" style="text-align:left; padding:10px 16px;">' + T('¿Es alguno de estos?') + '</div>' +
            lastSearchResults.map(resultRowHTML).join('') +
            '<div class="exercise-picker-footer">' +
            '<button type="button" onclick="renderCreateExerciseForm()" class="btn-outline" style="width:100%;">' + T('Ninguno, crear nuevo') + '</button>' +
            '</div>';
    } else {
        renderCreateExerciseForm();
    }
}

function renderCreateExerciseForm() {
    const box = document.getElementById('exercisePickerResults');
    const primaryCheckboxes = MUSCLE_OPTIONS.map(([value, label]) =>
        '<label><input type="checkbox" class="new-ex-primary" value="' + value + '"> ' + label + '</label>'
    ).join('');
    const secondaryCheckboxes = MUSCLE_OPTIONS.map(([value, label]) =>
        '<label><input type="checkbox" class="new-ex-secondary" value="' + value + '"> ' + label + '</label>'
    ).join('');
    box.innerHTML =
        '<div class="exercise-picker-create-form">' +
        '<input id="newExName" type="text" value="' + lastSearchQuery.replace(/"/g, '&quot;') + '" placeholder="' + T('Nombre del ejercicio') + '">' +
        '<div style="font-size:0.75rem; color:#888; margin-bottom:4px;">' + T('Músculos primarios (los que más trabajan)') + '</div>' +
        '<div class="exercise-picker-muscle-grid">' + primaryCheckboxes + '</div>' +
        '<div style="font-size:0.75rem; color:#888; margin:8px 0 4px;">' + T('Músculos secundarios (opcional)') + '</div>' +
        '<div class="exercise-picker-muscle-grid">' + secondaryCheckboxes + '</div>' +
        '<input id="newExCategory" type="text" placeholder="' + T('Categoría (opcional)') + '">' +
        '<input id="newExEquipment" type="text" placeholder="' + T('Equipo (opcional)') + '">' +
        '<div id="newExError" class="exercise-picker-error"></div>' +
        '<button type="button" onclick="submitNewExercise()" class="btn" style="width:100%;">' + T('Crear y usar') + '</button>' +
        '</div>';
}

function submitNewExercise() {
    const box = document.getElementById('exercisePickerResults');
    const name = document.getElementById('newExName').value.trim();
    const muscles = Array.from(box.querySelectorAll('input.new-ex-primary:checked')).map(c => c.value);
    const secondaryMuscles = Array.from(box.querySelectorAll('input.new-ex-secondary:checked')).map(c => c.value);
    const errorBox = document.getElementById('newExError');
    if (!name || !muscles.length) {
        errorBox.textContent = !name ? T('El nombre es obligatorio.') : T('Elige al menos un músculo primario.');
        errorBox.style.display = 'block';
        return;
    }
    fetch('/api/exercises/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            name: name,
            muscles: muscles,
            secondary_muscles: secondaryMuscles,
            category: document.getElementById('newExCategory').value.trim(),
            equipment: document.getElementById('newExEquipment').value.trim(),
        })
    })
    .then(r => r.json())
    .then(data => {
        if (!data.ok) {
            errorBox.textContent = data.error || T('No se pudo crear el ejercicio.');
            errorBox.style.display = 'block';
            return;
        }
        selectExercise(data.name);
    });
}

function selectExercise(name) {
    if (pickerReplaceUrl) {
        const payload = Object.assign({exercise: name}, pickerReplaceExtra || {});
        fetch(pickerReplaceUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(data => {
            if (!data.ok) {
                showPickerErrorToast(T('No se pudo reemplazar el ejercicio.'));
                return;
            }
            window.location.reload();
        });
        closeExercisePicker();
        return;
    }
    const field = document.querySelector('[name="exercise"]');
    field.value = name;
    closeExercisePicker();
    // En el entreno no hay nada más que rellenar: elegir = añadir. En
    // rutinas (series/reps/RIR) el formulario no lleva data-autosubmit.
    const form = field.closest('form');
    if (form && form.dataset.autosubmit === '1') {
        form.classList.add('is-submitting');
        const title = form.querySelector('.add-exercise-tile strong');
        if (title) title.textContent = T('Añadiendo {name}…').replace('{name}', name);
        HTMLFormElement.prototype.submit.call(form);
        return;
    }
    const chip = document.getElementById('selectedExerciseChip');
    chip.textContent = name;
    chip.classList.add('visible');
}

function resetExercisePickerResults() {
    lastSearchResults = [];
    lastSearchQuery = '';
    const box = document.getElementById('exercisePickerResults');
    box.innerHTML = '<div class="exercise-picker-hint">' + T('Escribe al menos 2 letras para buscar.') + '</div>';
    fetch('/api/exercises/search?q=')
        .then(r => r.json())
        .then(results => {
            if (!results.length) return;
            box.innerHTML = '<div class="exercise-picker-hint" style="text-align:left; padding:10px 16px; font-weight:600;">' + T('Favoritos') + '</div>' +
                results.map(resultRowHTML).join('');
        });
}

function openExercisePicker(replaceUrl, replaceExtra) {
    pickerReplaceUrl = replaceUrl || null;
    pickerReplaceExtra = replaceExtra || null;
    document.getElementById('exercisePickerBackdrop').classList.add('open');
    document.getElementById('exercisePickerSheet').classList.add('open');
    document.body.style.overflow = 'hidden';
    resetExercisePickerResults();
    const input = document.getElementById('exercisePickerSearchInput');
    input.value = '';
    setTimeout(() => input.focus(), 50);
}

function closeExercisePicker() {
    document.getElementById('exercisePickerBackdrop').classList.remove('open');
    document.getElementById('exercisePickerSheet').classList.remove('open');
    document.body.style.overflow = '';
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeExercisePicker();
});

function validateExerciseChosen() {
    const val = document.querySelector('[name="exercise"]').value.trim();
    if (!val) {
        showPickerErrorToast(T('Elige un ejercicio del catálogo primero.'));
        return false;
    }
    return true;
}

function showPickerErrorToast(message) {
    const existing = document.querySelector('.picker-error-toast');
    if (existing) existing.remove();
    if (pickerErrorTimeout) clearTimeout(pickerErrorTimeout);

    const toast = document.createElement('div');
    toast.className = 'picker-error-toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    void toast.offsetWidth;
    toast.classList.add('visible');

    pickerErrorTimeout = setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 250);
    }, 2500);
}
