// ─── TiempoLuarca Frontend ───────────────────────────────────────────────────

const BASE = window.__BASE || '/';
function apiUrl(path) { return BASE + path; }

// Funciones de fecha/hora LOCAL (nunca UTC) para comparar con timestamps del forecast
function localDateStr(d) {
    d = d || new Date();
    return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}
function localHourStr(d) {
    d = d || new Date();
    return localDateStr(d) + 'T' + String(d.getHours()).padStart(2,'0');
}
function localNowMins() {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
}

const SCORE_COLORS = {
    10: '#00C853', 9: '#64DD17', 8: '#AEEA00', 7: '#FFD600', 6: '#FFAB00',
    5: '#FF6D00', 4: '#FF3D00', 3: '#E53935', 2: '#F44336', 1: '#EF5350'
};

const WIND_DIRS = {
    N: 0, NNE: 22.5, NE: 45, ENE: 67.5, E: 90, ESE: 112.5, SE: 135, SSE: 157.5,
    S: 180, SSW: 202.5, SW: 225, WSW: 247.5, W: 270, WNW: 292.5, NW: 315, NNW: 337.5
};

const DAY_NAMES = ['Domingo', 'Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado'];
const DAY_SHORT = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab'];

let forecastData = [];
let selectedDate = null;
let currentData = null;
let summaryData = null;
let windUnit = localStorage.getItem('windUnit') || 'kn'; // 'kn' o 'kmh'

function knToDisplay(kn) {
    if (kn == null) return null;
    return windUnit === 'kmh' ? Math.round(kn * 1.852 * 10) / 10 : kn;
}
function windLabel() { return windUnit === 'kmh' ? 'km/h' : 'kn'; }

window.setUnit = function(unit) {
    windUnit = unit;
    localStorage.setItem('windUnit', unit);
    document.querySelectorAll('.unit-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.unit === unit);
    });
    // Re-render todo con la nueva unidad
    if (currentData) renderCurrent(currentData);
    if (summaryData) renderSummary(summaryData);
    if (forecastData.length && selectedDate) renderForecastDay(selectedDate);
    if (activeChart) drawDetailChart(activeChart);
};

// ─── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Restaurar unidad guardada
    document.querySelectorAll('.unit-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.unit === windUnit);
    });
    loadAll();
    setupFeedbackForm();
    setInterval(loadAll, 15 * 60 * 1000);
});

async function loadAll() {
    await Promise.all([
        loadCurrent(),
        loadSummary(),
        loadForecast(),
        loadExtended(),
        loadTides(),
        loadFeedbackHistory(),
    ]);
}

// ─── Current ─────────────────────────────────────────────────────────────────

async function loadCurrent() {
    try {
        const res = await fetch(apiUrl('api/current'));
        const data = await res.json();
        renderAlerts(data.alertas || []);
        renderCurrent(data);
    } catch (e) {
        console.error('Error loading current:', e);
    }
}

function renderCurrent(data) {
    currentData = data;
    // Update time
    if (data.updated) {
        const d = new Date(data.updated);
        document.getElementById('lastUpdate').textContent =
            `Actualizado: ${d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}`;
    }

    // Score ring
    const score = data.score;
    if (score) {
        const s = score.score;
        const color = score.color;
        document.getElementById('scoreNumber').textContent = s;
        document.getElementById('scoreNumber').style.color = color;
        document.getElementById('scoreLabel').textContent = score.label;
        document.getElementById('scoreLabel').style.color = color;

        // Tendencia
        const trend = score.tendencia;
        const trendEl = document.getElementById('scoreTrend');
        if (trendEl && trend) {
            const trendIcons = { mejorando: '&#9650;', empeorando: '&#9660;', estable: '&#9654;' };
            const trendColors = { mejorando: '#00C853', empeorando: '#F44336', estable: '#FFAB00' };
            const trendLabels = { mejorando: 'Mejorando', empeorando: 'Empeorando', estable: 'Estable' };
            trendEl.innerHTML = `<span style="color:${trendColors[trend]}">${trendIcons[trend]} ${trendLabels[trend]}</span>`;
            // Mostrar contexto si hay diferencia entre ahora y 5h
            if (score.score_ahora && score.score_ahora !== s) {
                trendEl.innerHTML += ` <span class="trend-detail">Ahora: ${score.score_ahora} · Prox. 5h: ${score.score_5h}</span>`;
            }
        }

        document.getElementById('scoreRecommendation').textContent = score.recomendacion;

        // Animate ring: 10=full, 1=empty
        const ring = document.getElementById('ringFg');
        const circumference = 2 * Math.PI * 54;
        const pct = (s - 1) / 9; // 10=full, 1=empty
        ring.style.strokeDashoffset = circumference * (1 - pct);
        ring.style.stroke = color;

        // Score bars (seguridad)
        setScoreBar('barViento', score.scores.viento);
        setScoreBar('barOleaje', score.scores.oleaje);
    }

    // Wind barb + weather emoji en el score principal
    const obs = data.observacion;
    if (obs) {
        renderWindBarb(obs.viento_vel_nudos, obs.viento_dir);
    }
    // Emoji del cielo basado en nubosidad y lluvia
    const fcNowPre = data.forecast_now;
    const emojiEl = document.getElementById('weatherEmoji');
    if (emojiEl && fcNowPre) {
        const nub = fcNowPre.nubosidad ?? 50;
        const lluvia = fcNowPre.prob_precipitacion ?? 0;
        let emoji;
        if (lluvia >= 70) emoji = '🌧️';       // lluvia fuerte
        else if (lluvia >= 40) emoji = '🌦️';   // lluvia y claros
        else if (nub >= 80) emoji = '☁️';       // cubierto
        else if (nub >= 50) emoji = '⛅';       // nubes y sol
        else if (nub >= 20) emoji = '🌤️';      // poco nublado
        else emoji = '☀️';                      // despejado
        emojiEl.textContent = emoji;
    }

    // Observation data
    if (obs) {
        document.getElementById('valViento').textContent =
            obs.viento_vel_nudos != null ? knToDisplay(obs.viento_vel_nudos) : '--';
        document.getElementById('cardViento').querySelector('.card-unit').textContent = windLabel();
        document.getElementById('valRacha').textContent =
            obs.viento_racha_nudos != null ? `Racha: ${knToDisplay(obs.viento_racha_nudos)} ${windLabel()} · ${windDirLabel(obs.viento_dir)}` : '';
        document.getElementById('valTemp').textContent =
            obs.temperatura != null ? obs.temperatura.toFixed(1) : '--';
        // Temp agua en pastilla temperatura
        const tempAgua = data.marine?.temp_agua;
        document.getElementById('valTempExtra').textContent =
            tempAgua != null ? `Agua: ${tempAgua.toFixed(1)}°` : '';
        // Presion en su pastilla
        if (obs.presion != null) {
            document.getElementById('valPresion').textContent = Math.round(obs.presion);
        }
        // Visibilidad (AEMET da km, Open-Meteo da metros)
        const visKm = obs.visibilidad != null ? obs.visibilidad : null;
        document.getElementById('valVisibilidad').textContent = visKm != null ? (visKm > 1 ? Math.round(visKm) : visKm.toFixed(1)) : '--';
    }

    // Datos del forecast para la hora actual
    const fcNow = data.forecast_now;

    // Visibilidad: si no hay de AEMET, usar Open-Meteo
    if (fcNow && fcNow.visibilidad != null && document.getElementById('valVisibilidad').textContent === '--') {
        const visKm = fcNow.visibilidad / 1000;
        document.getElementById('valVisibilidad').textContent = visKm >= 10 ? Math.round(visKm) : visKm.toFixed(1);
    }

    // Nubosidad: valor directo del forecast
    if (fcNow && fcNow.nubosidad != null) {
        const nub = Math.round(fcNow.nubosidad);
        document.getElementById('valNubes').textContent = nub;
        document.getElementById('valNubesExtra').textContent =
            nub <= 10 ? 'Despejado' : nub <= 30 ? 'Poco nublado' : nub <= 50 ? 'Intervalos' :
            nub <= 70 ? 'Nublado' : nub <= 90 ? 'Muy nublado' : 'Cubierto';

        // Icono dinamico
        const iconNubes = document.getElementById('iconNubes');
        if (iconNubes) {
            iconNubes.className = 'wi ' + (nub <= 15 ? 'wi-day-sunny' : nub <= 40 ? 'wi-day-cloudy' : nub <= 70 ? 'wi-cloudy' : 'wi-cloud');
        }
    }

    // Lluvia
    if (fcNow && fcNow.prob_precipitacion != null) {
        document.getElementById('valLluvia').textContent = Math.round(fcNow.prob_precipitacion) + '%';
    }

    // Tendencia de presion
    const pt = data.presion_trend;
    if (pt) {
        const arrow = pt.diff_6h > 0 ? '&#9650;' : pt.diff_6h < 0 ? '&#9660;' : '&#9654;';
        const sign = pt.diff_6h > 0 ? '+' : '';
        const trendColor = pt.diff_6h <= -3 ? '#F44336' : pt.diff_6h <= -1 ? '#FFAB00' : pt.diff_6h >= 1 ? '#00C853' : '#8895a7';
        document.getElementById('valPresionTrend').innerHTML =
            `<span style="color:${trendColor}">${arrow} ${sign}${pt.diff_6h} hPa/6h · ${pt.label}</span>`;
    }

    // Score bars
    const fc = data.score;
    if (fc && fc.scores) {
        setScoreBar('barLluvia', fc.scores.lluvia);
        setScoreBar('barVisibilidad', fc.scores.visibilidad);
        if (fc.scores.nubosidad != null) setScoreBar('barNubosidad', fc.scores.nubosidad);
        if (fc.scores.presion != null) setScoreBar('barPresion', fc.scores.presion);
        if (fc.scores.temperatura != null) setScoreBar('barTemp', fc.scores.temperatura);
    }

    // Marine — mostrar desglose swell + chop
    const marine = data.marine;
    if (marine) {
        document.getElementById('valOla').textContent =
            marine.ola_altura != null ? marine.ola_altura.toFixed(1) : '--';
        let extra = '';
        if (marine.swell_altura != null) {
            extra += `Fondo: ${marine.swell_altura.toFixed(1)}m ${marine.swell_periodo ? marine.swell_periodo.toFixed(0) + 's' : ''}`;
        }
        if (marine.viento_ola_altura != null) {
            extra += (extra ? ' · ' : '') + `Viento: ${marine.viento_ola_altura.toFixed(1)}m ${marine.viento_ola_periodo ? marine.viento_ola_periodo.toFixed(0) + 's' : ''}`;
        }
        if (!extra && marine.ola_periodo != null) {
            extra = `Periodo: ${marine.ola_periodo.toFixed(0)}s`;
        }
        document.getElementById('valPeriodo').textContent = extra;
    }

}

function renderWindBarb(speedKn, dirDeg) {
    const svg = document.getElementById('windBarbSvg');
    if (!svg) return;

    if (speedKn == null || dirDeg == null) {
        svg.innerHTML = '';
        return;
    }

    // Barba meteorologica estandar:
    // - Circulo en el centro (estacion)
    // - Palo sale del centro HACIA de donde viene el viento
    // - Barbas en el extremo lejano indican fuerza
    // - Sin punta de flecha
    //
    // Coordenadas: palo hacia y NEGATIVO (arriba en SVG)
    // rotate(0) → palo arriba → viento del NORTE
    // rotate(90) → palo a la derecha → viento del ESTE

    const cx = 30, cy = 30;
    const staffLen = 20;
    const barbLen = 10;
    const shortBarbLen = 6;
    const barbSpacing = 4;
    const pennantWidth = 4;

    let remaining = Math.round(speedKn / 5) * 5;
    const pennants = Math.floor(remaining / 50);
    remaining -= pennants * 50;
    const longBarbs = Math.floor(remaining / 10);
    remaining -= longBarbs * 10;
    const shortBarbs = Math.floor(remaining / 5);

    let elements = '';
    const strokeColor = speedKn <= 10 ? '#00C853' : speedKn <= 20 ? '#FFD600' : speedKn <= 30 ? '#FF6D00' : '#F44336';

    // Calma
    if (speedKn < 3) {
        elements = `<circle cx="0" cy="0" r="6" fill="none" stroke="${strokeColor}" stroke-width="2"/>`;
        svg.innerHTML = `<g transform="translate(${cx},${cy})">${elements}</g>`;
        return;
    }

    // Circulo estacion en el centro
    elements += `<circle cx="0" cy="0" r="2.5" fill="${strokeColor}" opacity="0.4"/>`;

    // Palo desde centro hacia arriba (y negativo)
    elements += `<line x1="0" y1="0" x2="0" y2="${-staffLen}" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round"/>`;

    // Barbas en el extremo lejano (y = -staffLen)
    let pos = -staffLen;

    for (let i = 0; i < pennants; i++) {
        elements += `<polygon points="0,${pos} ${barbLen},${pos + pennantWidth/2} 0,${pos + pennantWidth}" fill="${strokeColor}"/>`;
        pos += pennantWidth + 2;
    }
    for (let i = 0; i < longBarbs; i++) {
        elements += `<line x1="0" y1="${pos}" x2="${barbLen}" y2="${pos - 3}" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round"/>`;
        pos += barbSpacing;
    }
    for (let i = 0; i < shortBarbs; i++) {
        if (pennants === 0 && longBarbs === 0 && i === 0) pos = -staffLen + barbSpacing;
        elements += `<line x1="0" y1="${pos}" x2="${shortBarbLen}" y2="${pos - 2}" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round"/>`;
        pos += barbSpacing;
    }

    svg.innerHTML = `<g transform="translate(${cx},${cy}) rotate(${dirDeg})">${elements}</g>`;

}

function renderAlerts(alertas) {
    const container = document.getElementById('alertsContainer');
    if (!alertas || alertas.length === 0) {
        container.innerHTML = '';
        return;
    }
    const levelLabels = { rojo: 'Alerta roja', naranja: 'Alerta naranja', amarillo: 'Aviso amarillo' };
    const levelIcons = { rojo: 'wi-hurricane', naranja: 'wi-storm-warning', amarillo: 'wi-small-craft-advisory' };
    container.innerHTML = alertas.map(a => {
        const nivel = a.nivel || 'amarillo';
        return `<div class="alert-banner ${nivel}">
            <div class="alert-icon"><i class="wi ${levelIcons[nivel] || 'wi-storm-warning'}"></i></div>
            <div class="alert-content">
                <div class="alert-level">${levelLabels[nivel] || 'Aviso'} - ${a.zona || 'Costa asturiana'}</div>
                <div class="alert-headline">${a.headline || a.fenomeno || 'Aviso costero activo'}</div>
                ${a.descripcion ? `<div class="alert-detail">${a.descripcion}</div>` : ''}
                ${a.inicio ? `<div class="alert-detail">Desde: ${a.inicio.replace('T',' ').slice(0,16)} ${a.fin ? '· Hasta: ' + a.fin.replace('T',' ').slice(0,16) : ''}</div>` : ''}
            </div>
        </div>`;
    }).join('');
}

function setScoreBar(id, score) {
    const el = document.getElementById(id);
    if (!el) return;
    const pct = (score / 10) * 100;
    el.style.width = pct + '%';
    el.style.background = SCORE_COLORS[score] || '#666';
}

function windDirLabel(degrees) {
    if (degrees == null) return '';
    const dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const idx = Math.round(degrees / 22.5) % 16;
    return dirs[idx];
}

// ─── Summary ─────────────────────────────────────────────────────────────────

async function loadSummary() {
    try {
        const res = await fetch(apiUrl('api/summary'));
        const data = await res.json();
        renderSummary(data);
    } catch (e) {
        console.error('Error loading summary:', e);
    }
}

function renderSummary(data) {
    summaryData = data;
    const container = document.getElementById('summaryCards');
    const days = data.days || [];

    container.innerHTML = days.map(d => {
        if (!d || !d.disponible) {
            return `<div class="summary-card">
                <div class="summary-day">${d?.label || ''}</div>
                <div class="summary-date">${d?.fecha ? formatDate(d.fecha) : ''}</div>
                <div class="summary-unavailable">Sin datos</div>
            </div>`;
        }
        const color = d.color || '#666';
        return `<div class="summary-card clickable" style="border-top: 3px solid ${color}" onclick="goToForecastDay('${d.fecha}')">
            <div class="summary-day">${d.label}</div>
            <div class="summary-date">${formatDate(d.fecha)}</div>
            <div class="summary-score" style="color: ${color}">${d.score_medio}</div>
            <div class="summary-label" style="color: ${color}">${d.label_score || ''}</div>
            <div class="summary-details">
                <span style="color:${windColor(d.viento_max)}">Viento: ${d.viento_medio != null ? knToDisplay(d.viento_medio) : '--'} ${windLabel()} (max ${d.viento_max != null ? knToDisplay(d.viento_max) : '--'})</span><br>
                <span style="color:${swellColor(d.ola_max)}">Olas: ${d.ola_media || '--'}m (max ${d.ola_max || '--'}m)</span><br>
                <span style="color:${rainColor(d.precip_max)}">Lluvia: max ${d.precip_max || 0}%</span><br>
                <span style="color:${tempColor(d.temp_min)}">Temp: ${d.temp_min || '--'}° / ${d.temp_max || '--'}°</span>
            </div>
            ${d.mejor_ventana ? `<div class="summary-window">Mejor ventana: ${d.mejor_ventana.inicio} - ${d.mejor_ventana.fin}</div>` : ''}
        </div>`;
    }).join('');
}

window.goToForecastDay = function(date) {
    selectForecastDay(date);
    // Scroll a la sección de pronóstico
    document.querySelector('.forecast-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr + 'T12:00:00');
    return `${d.getDate()} ${['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][d.getMonth()]}`;
}

// ─── Forecast ────────────────────────────────────────────────────────────────

async function loadForecast() {
    try {
        const res = await fetch(apiUrl('api/forecast'));
        const data = await res.json();
        forecastData = data.forecast || [];
        renderForecastTabs();
        if (forecastData.length > 0) {
            const today = localDateStr();
            selectedDate = today;
            renderForecastDay(today);
        }
    } catch (e) {
        console.error('Error loading forecast:', e);
    }
}

function renderForecastTabs() {
    const dates = [...new Set(forecastData.map(f => f.timestamp.slice(0, 10)))];
    const container = document.getElementById('forecastTabs');
    container.innerHTML = dates.map(date => {
        const d = new Date(date + 'T12:00:00');
        const dayName = DAY_SHORT[d.getDay()];
        const dayNum = d.getDate();
        const isActive = date === selectedDate ? 'active' : '';
        return `<button class="forecast-tab ${isActive}" onclick="selectForecastDay('${date}')">${dayName} ${dayNum}</button>`;
    }).join('');
}

window.selectForecastDay = function(date) {
    selectedDate = date;
    renderForecastTabs();
    renderForecastDay(date);
};

function renderForecastDay(date) {
    const hours = forecastData.filter(f => f.timestamp.startsWith(date));
    renderForecastChart(hours);
    renderForecastTable(hours);
}

function renderForecastChart(hours) {
    const container = document.getElementById('forecastChart');
    container.innerHTML = hours.map(h => {
        const score = h.score || 5;
        const color = SCORE_COLORS[score] || '#666';
        const height = (score / 10) * 100;
        const time = h.timestamp.slice(11, 16);
        return `<div class="chart-bar" style="height: ${height}%; background: ${color}">
            <div class="chart-bar-tooltip">${time}: ${score}/10</div>
        </div>`;
    }).join('');
}

// Colores por valor: devuelve color del SCORE_COLORS segun umbrales (10=bueno, 1=malo)
function windColor(kn) {
    if (kn == null) return '';
    if (kn <= 5) return SCORE_COLORS[10];
    if (kn <= 8) return SCORE_COLORS[9];
    if (kn <= 10) return SCORE_COLORS[8];
    if (kn <= 12) return SCORE_COLORS[7];
    if (kn <= 15) return SCORE_COLORS[6];
    if (kn <= 18) return SCORE_COLORS[5];
    if (kn <= 20) return SCORE_COLORS[4];
    if (kn <= 25) return SCORE_COLORS[3];
    if (kn <= 30) return SCORE_COLORS[2];
    return SCORE_COLORS[1];
}
function swellColor(m) {
    if (m == null) return '';
    if (m <= 0.3) return SCORE_COLORS[10];
    if (m <= 0.6) return SCORE_COLORS[9];
    if (m <= 0.9) return SCORE_COLORS[8];
    if (m <= 1.2) return SCORE_COLORS[7];
    if (m <= 1.5) return SCORE_COLORS[6];
    if (m <= 1.8) return SCORE_COLORS[5];
    if (m <= 2.0) return SCORE_COLORS[4];
    if (m <= 2.5) return SCORE_COLORS[3];
    if (m <= 3.0) return SCORE_COLORS[2];
    return SCORE_COLORS[1];
}
function chopColor(m) {
    if (m == null) return '';
    if (m <= 0.1) return SCORE_COLORS[10];
    if (m <= 0.2) return SCORE_COLORS[9];
    if (m <= 0.3) return SCORE_COLORS[8];
    if (m <= 0.5) return SCORE_COLORS[7];
    if (m <= 0.7) return SCORE_COLORS[5];
    if (m <= 0.9) return SCORE_COLORS[4];
    if (m <= 1.2) return SCORE_COLORS[3];
    if (m <= 1.5) return SCORE_COLORS[2];
    return SCORE_COLORS[1];
}
function rainColor(pct) {
    if (pct == null) return '';
    if (pct <= 5) return SCORE_COLORS[10];
    if (pct <= 15) return SCORE_COLORS[9];
    if (pct <= 25) return SCORE_COLORS[8];
    if (pct <= 35) return SCORE_COLORS[7];
    if (pct <= 50) return SCORE_COLORS[6];
    if (pct <= 60) return SCORE_COLORS[5];
    if (pct <= 70) return SCORE_COLORS[4];
    if (pct <= 80) return SCORE_COLORS[3];
    if (pct <= 90) return SCORE_COLORS[2];
    return SCORE_COLORS[1];
}
function visColor(m) {
    if (m == null) return '';
    const km = m / 1000;
    if (km >= 20) return SCORE_COLORS[10];
    if (km >= 15) return SCORE_COLORS[9];
    if (km >= 10) return SCORE_COLORS[8];
    if (km >= 7) return SCORE_COLORS[7];
    if (km >= 5) return SCORE_COLORS[6];
    if (km >= 3) return SCORE_COLORS[5];
    if (km >= 2) return SCORE_COLORS[4];
    if (km >= 1) return SCORE_COLORS[3];
    return SCORE_COLORS[1];
}
function cloudColor(pct) {
    if (pct == null) return '';
    if (pct <= 10) return SCORE_COLORS[10];
    if (pct <= 25) return SCORE_COLORS[9];
    if (pct <= 40) return SCORE_COLORS[8];
    if (pct <= 50) return SCORE_COLORS[7];
    if (pct <= 60) return SCORE_COLORS[6];
    if (pct <= 70) return SCORE_COLORS[5];
    if (pct <= 80) return SCORE_COLORS[4];
    if (pct <= 90) return SCORE_COLORS[3];
    return SCORE_COLORS[2];
}
function tempColor(c) {
    if (c == null) return '';
    if (c < 5) return '#3b82f6';
    if (c < 10) return '#06b6d4';
    if (c < 15) return '#64DD17';
    if (c < 20) return '#AEEA00';
    if (c < 25) return '#FFD600';
    if (c < 30) return '#FF6D00';
    return '#FF3D00';
}

function renderForecastTable(hours) {
    const tbody = document.getElementById('forecastBody');
    const nowHour = localHourStr();
    tbody.innerHTML = hours.map(h => {
        const score = h.score || 5;
        const color = SCORE_COLORS[score] || '#666';
        const time = h.timestamp.slice(11, 16);
        const isNow = h.timestamp.slice(0, 13) === nowHour;
        const windDir = h.viento_dir != null ? h.viento_dir : '';
        const wc = windColor(h.viento_nudos);
        const rc = windColor(h.viento_racha_nudos);
        const sc = swellColor(h.swell_altura);
        const cc = chopColor(h.viento_ola_altura);
        const pc = rainColor(h.prob_precipitacion);
        const vc = visColor(h.visibilidad);
        const nc = cloudColor(h.nubosidad);
        const tc = tempColor(h.temperatura);
        // Swell con periodo
        const swellTxt = h.swell_altura != null
            ? h.swell_altura.toFixed(1) + 'm' + (h.swell_periodo != null ? ' <small>' + Math.round(h.swell_periodo) + 's</small>' : '')
            : (h.ola_altura != null ? h.ola_altura.toFixed(1) + 'm' : '--');
        const swellClr = h.swell_altura != null ? sc : swellColor(h.ola_altura);
        // Chop con periodo
        const chopTxt = h.viento_ola_altura != null
            ? h.viento_ola_altura.toFixed(1) + 'm' + (h.viento_ola_periodo != null ? ' <small>' + h.viento_ola_periodo.toFixed(0) + 's</small>' : '')
            : '--';
        // Visibilidad en km
        const visKm = h.visibilidad != null ? h.visibilidad / 1000 : null;
        const visTxt = visKm != null ? (visKm >= 10 ? Math.round(visKm) + 'km' : visKm.toFixed(1) + 'km') : '--';
        // Nubosidad
        const nubTxt = h.nubosidad != null ? Math.round(h.nubosidad) + '%' : '--';
        return `<tr class="${isNow ? 'current-hour' : ''}">
            <td><strong>${time}</strong>${isNow ? ' <small>AHORA</small>' : ''}</td>
            <td><span class="score-badge" style="background: ${color}">${score}</span></td>
            <td style="color:${wc}">${formatNum(knToDisplay(h.viento_nudos))} ${windLabel()} ${windDir ? `<span class="wind-arrow" style="transform: rotate(${windDir + 180}deg)">&#8593;</span>` : ''}</td>
            <td style="color:${rc}">${formatNum(knToDisplay(h.viento_racha_nudos))} ${windLabel()}</td>
            <td style="color:${swellClr}">${swellTxt}</td>
            <td style="color:${cc}">${chopTxt}</td>
            <td style="color:${pc}">${formatNum(h.prob_precipitacion)}%</td>
            <td style="color:${vc}">${visTxt}</td>
            <td style="color:${nc}">${nubTxt}</td>
            <td style="color:${tc}">${formatNum(h.temperatura)}°</td>
            <td style="color:${h.temp_agua != null ? tempColor(h.temp_agua) : ''}">${h.temp_agua != null ? h.temp_agua.toFixed(1) + '°' : '--'}</td>
        </tr>`;
    }).join('');
}

function formatNum(v) {
    if (v == null) return '--';
    return typeof v === 'number' ? Math.round(v * 10) / 10 : v;
}

// ─── Extended forecast (16 days) ──────────────────────────────────────────────

async function loadExtended() {
    try {
        const res = await fetch(apiUrl('api/extended'));
        const data = await res.json();
        renderExtended(data.days || []);
    } catch (e) {
        console.error('Error loading extended:', e);
    }
}

function renderExtended(days) {
    const container = document.getElementById('extendedContainer');
    if (!days.length) {
        container.innerHTML = '<p class="loading">Sin datos extendidos</p>';
        return;
    }

    container.innerHTML = days.map((d, i) => {
        const color = SCORE_COLORS[d.score] || '#666';
        const conf = d.fiable ? '' : ' low-confidence';
        const confBadge = d.fiable ? '' : '<span class="ext-low-badge">~</span>';

        // Emoji cielo
        const nub = d.nubosidad ?? 50;
        const lluvia = d.prob_precipitacion ?? 0;
        let emoji;
        if (lluvia >= 70) emoji = '🌧️';
        else if (lluvia >= 40) emoji = '🌦️';
        else if (nub >= 80) emoji = '☁️';
        else if (nub >= 50) emoji = '⛅';
        else if (nub >= 20) emoji = '🌤️';
        else emoji = '☀️';

        const fecha = d.fecha || '';
        const dayNum = fecha.slice(8, 10);
        const month = fecha.slice(5, 7);

        return `<div class="ext-day${conf}" style="border-top: 3px solid ${color}" onclick="goToForecastDay('${fecha}')">
            ${confBadge}
            <div class="ext-day-name">${d.dia}</div>
            <div class="ext-day-date">${dayNum}/${month}</div>
            <div class="ext-day-emoji">${emoji}</div>
            <div class="ext-day-score" style="color: ${color}">${d.score}</div>
            <div class="ext-day-label" style="color: ${color}">${d.label}</div>
            <div class="ext-day-details">
                <span style="color:${windColor(d.viento_max_kn)}">${knToDisplay(d.viento_max_kn)} ${windLabel()}</span>
                <span style="color:${swellColor(d.ola_max)}">${d.ola_max != null ? d.ola_max.toFixed(1) + 'm' : '--'}</span><br>
                <span style="color:${rainColor(d.prob_precipitacion)}">${d.prob_precipitacion ?? '--'}%</span>
                ${d.temp_min != null ? `<span style="color:${tempColor(d.temp_min)}">${Math.round(d.temp_min)}°/${Math.round(d.temp_max)}°</span>` : ''}
            </div>
        </div>`;
    }).join('');
}

// ─── Tides ───────────────────────────────────────────────────────────────────

let tidesData = null;
let selectedTideStation = 'navia';

async function loadTides() {
    try {
        const res = await fetch(apiUrl('api/tides'));
        tidesData = await res.json();
        drawTideChart();
    } catch (e) {
        console.error('Error loading tides:', e);
    }
}

window.selectTideStation = function(station) {
    selectedTideStation = station;
    document.querySelectorAll('.tide-tab').forEach(b => {
        b.classList.toggle('active', b.dataset.station === station);
    });
    drawTideChart();
};

function drawTideChart() {
    if (!tidesData) return;
    const tides = tidesData[selectedTideStation] || [];
    if (tides.length < 2) return;

    // Parsear puntos reales
    const baseDate = tides[0].fecha;
    const realPoints = tides.map(t => {
        const [hh, mm] = (t.hora || '0:0').split(':').map(Number);
        const dayOffset = t.fecha === baseDate ? 0 : 1;
        return {
            mins: dayOffset * 1440 + hh * 60 + mm,
            height: t.altura,
            tipo: (t.tipo || '').toLowerCase(),
            hora: t.hora,
        };
    });

    // Calcular medias para extrapolar
    const pleaH = realPoints.filter(p => p.tipo.includes('plea')).map(p => p.height);
    const bajaH = realPoints.filter(p => !p.tipo.includes('plea')).map(p => p.height);
    const avgPlea = pleaH.length ? pleaH.reduce((a, b) => a + b) / pleaH.length : 3;
    const avgBaja = bajaH.length ? bajaH.reduce((a, b) => a + b) / bajaH.length : 1;

    // Duracion media entre puntos consecutivos (plea->baja o baja->plea)
    let avgDur = 0;
    for (let i = 0; i < realPoints.length - 1; i++) avgDur += realPoints[i + 1].mins - realPoints[i].mins;
    avgDur /= (realPoints.length - 1);

    // Extrapolar: anadir puntos antes y despues para cubrir todo el dia + "ahora"
    const now = new Date();
    const nowMins = now.getHours() * 60 + now.getMinutes();
    const allPoints = [...realPoints];

    // Extrapolar hacia atras hasta cubrir 00:00
    while (allPoints[0].mins > 0) {
        const first = allPoints[0];
        const newTipo = first.tipo.includes('plea') ? 'bajamar' : 'pleamar';
        const newH = newTipo.includes('plea') ? avgPlea : avgBaja;
        const newMins = first.mins - avgDur;
        const hh = Math.floor(((newMins % 1440) + 1440) % 1440 / 60);
        const mm = Math.round(((newMins % 1440) + 1440) % 1440 % 60);
        allPoints.unshift({
            mins: newMins, height: newH, tipo: newTipo,
            hora: String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0'),
            estimated: true,
        });
    }

    // Extrapolar hacia adelante hasta cubrir al menos 1h despues de "ahora" y fin del dia
    const endTarget = Math.max(1439, nowMins + 60);
    while (allPoints[allPoints.length - 1].mins < endTarget) {
        const last = allPoints[allPoints.length - 1];
        const newTipo = last.tipo.includes('plea') ? 'bajamar' : 'pleamar';
        const newH = newTipo.includes('plea') ? avgPlea : avgBaja;
        const newMins = last.mins + avgDur;
        const hh = Math.floor((newMins % 1440) / 60);
        const mm = Math.round(newMins % 1440 % 60);
        allPoints.push({
            mins: newMins, height: newH, tipo: newTipo,
            hora: String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0'),
            estimated: true,
        });
    }

    // Generar curva coseno suave entre todos los puntos
    const curve = [];
    for (let i = 0; i < allPoints.length - 1; i++) {
        const p0 = allPoints[i];
        const p1 = allPoints[i + 1];
        const dur = p1.mins - p0.mins;
        if (dur <= 0) continue;
        const steps = Math.max(Math.round(dur / 3), 10);
        for (let s = 0; s <= steps; s++) {
            const t = s / steps;
            const h = p0.height + (p1.height - p0.height) * (0.5 - 0.5 * Math.cos(Math.PI * t));
            curve.push({ mins: p0.mins + t * dur, height: h });
        }
    }
    if (curve.length === 0) return;

    // Rango visible: 00:00 hasta max(23:59, ahora+1h)
    const viewStart = 0;
    const viewEnd = Math.max(1439, nowMins + 60);
    const visibleCurve = curve.filter(c => c.mins >= viewStart && c.mins <= viewEnd);
    if (visibleCurve.length === 0) return;

    // ─── Canvas setup ────
    const canvas = document.getElementById('tideCanvas');
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;
    ctx.clearRect(0, 0, W, H);

    const pad = { top: 28, right: 15, bottom: 28, left: 40 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    const heights = visibleCurve.map(c => c.height);
    const minH = Math.min(...heights) - 0.15;
    const maxH = Math.max(...heights) + 0.15;

    function xPos(m) { return pad.left + ((m - viewStart) / (viewEnd - viewStart)) * plotW; }
    function yPos(h) { return pad.top + plotH - ((h - minH) / (maxH - minH)) * plotH; }

    // ─── Bandas alternas por dia ────
    // viewStart/viewEnd estan en minutos desde 00:00 del dia base
    // dia 0 = 0..1439, dia 1 = 1440..2879, etc
    for (let dayStart = 0; dayStart <= viewEnd; dayStart += 1440) {
        const dayIdx = dayStart / 1440;
        if (dayIdx % 2 === 1) {
            const x0 = Math.max(xPos(dayStart), pad.left);
            const x1 = Math.min(xPos(dayStart + 1440), pad.left + plotW);
            if (x1 > x0) {
                ctx.fillStyle = 'rgba(255,255,255,0.03)';
                ctx.fillRect(x0, pad.top, x1 - x0, plotH);
            }
        }
        // Separador y etiqueta de dia a las 00:00
        if (dayStart > viewStart && dayStart < viewEnd) {
            const xDay = xPos(dayStart);
            ctx.strokeStyle = '#ffffff18';
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(xDay, pad.top); ctx.lineTo(xDay, pad.top + plotH); ctx.stroke();
        }
    }

    // ─── Grid horizontal ────
    ctx.strokeStyle = '#1e3050';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
        const h = minH + ((maxH - minH) / 4) * i;
        const y = yPos(h);
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + plotW, y); ctx.stroke();
        ctx.fillStyle = '#8895a7';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText((Math.round(h * 10) / 10) + 'm', pad.left - 6, y + 4);
    }

    // ─── Horas en eje X ────
    ctx.fillStyle = '#8895a7';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    for (let m = 0; m <= viewEnd; m += 120) {
        const x = xPos(m);
        const hh = Math.floor(m / 60);
        ctx.fillText(String(hh).padStart(2, '0') + ':00', x, H - pad.bottom + 14);
        ctx.strokeStyle = '#1e305030';
        ctx.lineWidth = 0.5;
        ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + plotH); ctx.stroke();
    }

    // ─── Area degradado bajo curva ────
    const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
    grad.addColorStop(0, 'rgba(6, 182, 212, 0.2)');
    grad.addColorStop(1, 'rgba(6, 182, 212, 0.01)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(xPos(visibleCurve[0].mins), pad.top + plotH);
    for (const pt of visibleCurve) ctx.lineTo(xPos(pt.mins), yPos(pt.height));
    ctx.lineTo(xPos(visibleCurve[visibleCurve.length - 1].mins), pad.top + plotH);
    ctx.closePath();
    ctx.fill();

    // ─── Curva: solida para datos reales, discontinua para estimados ────
    const firstReal = realPoints[0].mins;
    const lastReal = realPoints[realPoints.length - 1].mins;

    // Parte estimada izquierda
    const leftEst = visibleCurve.filter(c => c.mins <= firstReal);
    if (leftEst.length > 1) {
        ctx.strokeStyle = '#06b6d460';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        leftEst.forEach((c, i) => { const x = xPos(c.mins), y = yPos(c.height); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // Parte real (solida)
    const realCurve = visibleCurve.filter(c => c.mins >= firstReal && c.mins <= lastReal);
    if (realCurve.length > 1) {
        ctx.strokeStyle = '#06b6d4';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        realCurve.forEach((c, i) => { const x = xPos(c.mins), y = yPos(c.height); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
        ctx.stroke();
    }

    // Parte estimada derecha
    const rightEst = visibleCurve.filter(c => c.mins >= lastReal);
    if (rightEst.length > 1) {
        ctx.strokeStyle = '#06b6d460';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        rightEst.forEach((c, i) => { const x = xPos(c.mins), y = yPos(c.height); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // ─── Puntos de pleamar/bajamar (solo reales) ────
    for (const p of realPoints) {
        const x = xPos(p.mins), y = yPos(p.height);
        const isPlea = p.tipo.includes('plea');

        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fillStyle = isPlea ? '#FFAB00' : '#3b82f6';
        ctx.fill();
        ctx.strokeStyle = '#0a1628';
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.fillStyle = isPlea ? '#FFAB00' : '#3b82f6';
        ctx.font = 'bold 11px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        const ly = isPlea ? y - 14 : y + 18;
        ctx.fillText(p.hora, x, ly);
        ctx.font = '10px -apple-system, sans-serif';
        ctx.fillText(p.height.toFixed(1) + 'm', x, ly + (isPlea ? -12 : 12));
    }

    // ─── Marcador AHORA ────
    if (nowMins >= viewStart && nowMins <= viewEnd) {
        const xNow = xPos(nowMins);

        // Linea vertical blanca
        ctx.strokeStyle = '#ffffffcc';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(xNow, pad.top);
        ctx.lineTo(xNow, pad.top + plotH);
        ctx.stroke();

        // Interpolar altura actual sobre la curva completa
        let currentH = null;
        for (let i = 0; i < curve.length - 1; i++) {
            if (curve[i].mins <= nowMins && curve[i + 1].mins >= nowMins) {
                const t = (nowMins - curve[i].mins) / (curve[i + 1].mins - curve[i].mins);
                currentH = curve[i].height + t * (curve[i + 1].height - curve[i].height);
                break;
            }
        }

        if (currentH !== null) {
            const yNow = yPos(currentH);

            // Circulo blanco con centro cyan
            ctx.beginPath();
            ctx.arc(xNow, yNow, 7, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff';
            ctx.fill();
            ctx.strokeStyle = '#0a1628';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(xNow, yNow, 4, 0, Math.PI * 2);
            ctx.fillStyle = '#06b6d4';
            ctx.fill();

            // Etiqueta AHORA arriba
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 10px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('AHORA', xNow, pad.top - 8);

            // Altura actual al lado
            ctx.fillStyle = '#06b6d4';
            ctx.font = '11px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(currentH.toFixed(1) + 'm', xNow + 10, yNow - 2);
        }
    }

    // ─── Info: subiendo/bajando + proximas mareas ────
    renderTideInfo(allPoints, nowMins);
}

function renderTideInfo(allPts, nowMins) {
    const container = document.getElementById('tideNext');

    const past = allPts.filter(p => p.mins <= nowMins);
    const upcoming = allPts.filter(p => p.mins > nowMins);
    const lastEvent = past.length ? past[past.length - 1] : null;

    let html = '';

    // Tendencia actual
    if (lastEvent && upcoming.length > 0) {
        const rising = upcoming[0].tipo.includes('plea');
        const arrow = rising ? '&#9650;' : '&#9660;';
        const color = rising ? '#FFAB00' : '#3b82f6';
        const label = rising ? 'Subiendo' : 'Bajando';
        html += `<div class="tide-next-item" style="border-top: 3px solid ${color}">
            <div class="tide-next-type" style="color: ${color}">${arrow} ${label}</div>
            <div class="tide-next-time" style="font-size: 0.85rem">Marea actual</div>
        </div>`;
    }

    // Proximas 3 mareas
    for (const p of upcoming.slice(0, 3)) {
        const isPlea = p.tipo.includes('plea');
        const cls = isPlea ? 'pleamar' : 'bajamar';
        const label = isPlea ? 'Pleamar' : 'Bajamar';
        const est = p.estimated ? ' ~' : '';
        html += `<div class="tide-next-item ${cls}">
            <div class="tide-next-type">${label}${est}</div>
            <div class="tide-next-time">${p.hora}</div>
            <div class="tide-next-height">${p.height.toFixed(2)}m</div>
        </div>`;
    }

    container.innerHTML = html;
}

window.addEventListener('resize', () => {
    if (tidesData) drawTideChart();
});

// ─── Moon ────────────────────────────────────────────────────────────────────

function renderMoon() {
    const container = document.getElementById('moonSection');
    if (!container) return;

    const now = new Date();

    // Fase lunar: 0=nueva, 0.25=cuarto creciente, 0.5=llena, 0.75=cuarto menguante
    const ref = new Date(2000, 0, 6, 18, 14); // Luna nueva referencia
    const diff = (now - ref) / 86400000;
    const cycle = 29.53058867;
    const phase = ((diff % cycle) + cycle) % cycle / cycle;

    // Iluminación
    const illum = Math.round((1 - Math.cos(2 * Math.PI * phase)) / 2 * 100);

    // Nombre y emoji
    const phases = [
        { max: 0.0625, name: 'Luna nueva', emoji: '🌑' },
        { max: 0.1875, name: 'Creciente', emoji: '🌒' },
        { max: 0.3125, name: 'Cuarto creciente', emoji: '🌓' },
        { max: 0.4375, name: 'Gibosa creciente', emoji: '🌔' },
        { max: 0.5625, name: 'Luna llena', emoji: '🌕' },
        { max: 0.6875, name: 'Gibosa menguante', emoji: '🌖' },
        { max: 0.8125, name: 'Cuarto menguante', emoji: '🌗' },
        { max: 0.9375, name: 'Menguante', emoji: '🌘' },
        { max: 1.01, name: 'Luna nueva', emoji: '🌑' },
    ];
    const current = phases.find(p => phase < p.max);

    // Próximas fases principales, ordenadas por fecha
    const mainPhases = [
        { target: 0, emoji: '🌑', label: 'Nueva' },
        { target: 0.25, emoji: '🌓', label: 'C. creciente' },
        { target: 0.5, emoji: '🌕', label: 'Llena' },
        { target: 0.75, emoji: '🌗', label: 'C. menguante' },
    ];
    const upcoming = mainPhases.map(p => {
        let d = (p.target - phase) * cycle;
        if (d <= 0) d += cycle;
        const date = new Date(now.getTime() + d * 86400000);
        const dateStr = date.getDate() + ' ' + ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][date.getMonth()];
        return { ...p, days: d, dateStr };
    }).sort((a, b) => a.days - b.days);

    const upcomingHtml = upcoming.map(p =>
        `<div class="moon-upcoming-item"><span class="moon-emoji">${p.emoji}</span>${p.dateStr}</div>`
    ).join('');

    container.innerHTML = `
        <div class="moon-emoji-big">${current.emoji}</div>
        <div class="moon-info">
            <div class="moon-phase-name">${current.name}</div>
            <div class="moon-detail">Iluminacion: ${illum}%</div>
            <div class="moon-upcoming">${upcomingHtml}</div>
        </div>
    `;

    // Dibujar la luna gráficamente
}

// Renderizar luna al cargar
document.addEventListener('DOMContentLoaded', () => renderMoon());

// ─── Collapsible sections ─────────────────────────────────────────────────────

window.toggleSection = function(id) {
    const body = document.getElementById(id + 'Body');
    const icon = document.getElementById(id + 'Icon');
    if (!body) return;
    const isOpen = body.style.display !== 'none';
    body.style.display = isOpen ? 'none' : 'block';
    if (icon) icon.classList.toggle('open', !isOpen);

    // Lazy-load: cargar iframe solo al abrir por primera vez
    if (!isOpen) {
        if (id === 'windy') {
            const frame = document.getElementById('windyFrame');
            if (!frame.src || frame.src === '' || frame.src === window.location.href) {
                selectMap('wind');
            }
        }
        if (id === 'portus') {
            const frame = document.getElementById('portusFrame');
            if (!frame.src || frame.src === '' || frame.src === window.location.href) {
                selectPortus('oleaje');
            }
        }
    }
};

// ─── Windy Maps ──────────────────────────────────────────────────────────────

const WINDY_BASE = 'https://embed.windy.com/embed.html?type=map&location=coordinates&metricRain=mm&metricTemp=%C2%B0C&metricWind=km%2Fh&zoom=8&level=surface&lat=43.54&lon=-6.54&message=true';

const MAP_CONFIG = {
    wind:      { overlay: 'wind', product: 'ecmwf' },
    waves:     { overlay: 'waves', product: 'ecmwf' },
    rain:      { overlay: 'rain', product: 'ecmwf' },
    clouds:    { overlay: 'clouds', product: 'ecmwf' },
    satellite: { overlay: 'satellite', product: 'ecmwf' },
    radar:     { overlay: 'radar', product: 'ecmwf' },
};

window.selectMap = function(mapId) {
    document.querySelectorAll('.map-tab:not(.portus-tab)').forEach(b => {
        b.classList.toggle('active', b.dataset.map === mapId);
    });
    const config = MAP_CONFIG[mapId];
    if (!config) return;
    const frame = document.getElementById('windyFrame');
    const newSrc = `${WINDY_BASE}&overlay=${config.overlay}&product=${config.product}`;
    if (frame.src !== newSrc) frame.src = newSrc;
};

// ─── Portus Maps ─────────────────────────────────────────────────────────────

const PORTUS_BASE = 'https://portus.puertos.es/#/predictionWidget';

const PORTUS_CONFIG = {
    oleaje:      { resourceId: 'oleaje-atl', var: 'WAVE', vec: true },
    viento:      { resourceId: 'viento', var: 'WIND', vec: true },
    temperatura: { resourceId: 'temperatura', var: 'WATER_TEMP', vec: false },
    corrientes:  { resourceId: 'corriente', var: 'CURRENTS', vec: true },
    nivmar:      { resourceId: 'nivmar', var: 'SEA_LEVEL', vec: false },
};

window.selectPortus = function(mapId) {
    document.querySelectorAll('.portus-tab').forEach(b => {
        b.classList.toggle('active', b.dataset.portus === mapId);
    });
    const config = PORTUS_CONFIG[mapId];
    if (!config) return;
    const frame = document.getElementById('portusFrame');
    const newSrc = `${PORTUS_BASE}?resourceId=${config.resourceId}&var=${config.var}&zoom=8&lat=43.54&lon=-6.54&vec=${config.vec}&locale=es&theme=dark`;
    if (frame.src !== newSrc) frame.src = newSrc;
};

// ─── Feedback ────────────────────────────────────────────────────────────────

function setupFeedbackForm() {
    // Set today's date
    const today = localDateStr();
    document.getElementById('fbDate').value = today;

    // Toggle buttons
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const group = btn.parentElement;
            group.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    // Score selector
    const scoreButtons = document.querySelectorAll('#scoreSelector button');
    scoreButtons.forEach(btn => {
        const val = parseInt(btn.dataset.val);
        btn.style.background = SCORE_COLORS[val];
        btn.style.color = val <= 2 ? '#fdd' : 'white';
        btn.addEventListener('click', () => {
            scoreButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    // Submit
    document.getElementById('feedbackForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const msg = document.getElementById('formMessage');

        const activeScore = form.querySelector('#scoreSelector button.active');
        if (!activeScore) {
            msg.textContent = 'Selecciona una puntuacion';
            msg.style.color = '#FF3D00';
            return;
        }

        const activeSalida = form.querySelector('.toggle-btn.active[data-field="salida"]');

        const payload = {
            date: form.date.value,
            salida: parseInt(activeSalida?.dataset.value || '0'),
            score_real: parseInt(activeScore.dataset.val),
            viento_real: form.viento_real.value || null,
            oleaje_real: form.oleaje_real.value || null,
            lluvia_real: form.lluvia_real.value || null,
            comentario: form.comentario.value || null,
        };

        try {
            const res = await fetch(apiUrl('api/feedback'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (res.ok) {
                msg.textContent = 'Feedback guardado!';
                msg.style.color = '#00C853';
                form.reset();
                document.getElementById('fbDate').value = today;
                scoreButtons.forEach(b => b.classList.remove('active'));
                loadFeedbackHistory();
            } else {
                throw new Error('Error del servidor');
            }
        } catch (err) {
            msg.textContent = 'Error al guardar: ' + err.message;
            msg.style.color = '#FF3D00';
        }
    });
}

async function loadFeedbackHistory() {
    try {
        const res = await fetch(apiUrl('api/feedback'));
        const data = await res.json();
        renderFeedbackHistory(data.feedback || []);
    } catch (e) {
        console.error('Error loading feedback:', e);
    }
}

function renderFeedbackHistory(items) {
    const container = document.getElementById('feedbackHistory');
    if (items.length === 0) {
        container.innerHTML = '<p class="loading">Sin feedback todavia. Registra tu primera salida!</p>';
        return;
    }
    container.innerHTML = items.slice(0, 10).map(fb => {
        const sailed = fb.salida ? '&#9973;' : '&#127961;';
        const appColor = SCORE_COLORS[fb.score_app] || '#666';
        const realColor = SCORE_COLORS[fb.score_real] || '#666';
        return `<div class="feedback-entry">
            <div>
                <span class="feedback-entry-date">${fb.date}</span>
                <span>${sailed}</span>
                ${fb.comentario ? `<br><small style="color: var(--text-dim)">${fb.comentario}</small>` : ''}
            </div>
            <div class="feedback-entry-scores">
                <div class="fb-app">
                    <span style="color: ${appColor}">${fb.score_app || '-'}</span>
                    App
                </div>
                <div class="fb-real">
                    <span style="color: ${realColor}">${fb.score_real}</span>
                    Real
                </div>
            </div>
        </div>`;
    }).join('');
}

// ─── Detail Charts (expandible en cada pastilla) ─────────────────────────────

let activeChart = null; // 'viento' | 'oleaje' | 'lluvia' | 'temperatura' | null

const CHART_CONFIG = {
    viento: {
        title: 'Viento - proximas 48h',
        series: [
            { key: 'viento_nudos', label: 'Viento', color: '#3b82f6', convert: v => knToDisplay(v) },
            { key: 'viento_racha_nudos', label: 'Racha', color: '#f97316', convert: v => knToDisplay(v), dashed: true },
        ],
        unitFn: () => windLabel(),
    },
    oleaje: {
        title: 'Oleaje - proximas 48h',
        series: [
            { key: 'swell_altura', label: 'Mar de fondo (m)', color: '#06b6d4', convert: v => v },
            { key: 'viento_ola_altura', label: 'Mar de viento (m)', color: '#f97316', convert: v => v },
            { key: 'ola_altura', label: 'Ola total (m)', color: '#8b5cf6', convert: v => v, dashed: true },
            { key: 'swell_periodo', label: 'Periodo fondo (s)', color: '#00C853', convert: v => v, secondary: true },
            { key: 'viento_ola_periodo', label: 'Periodo viento (s)', color: '#FFD600', convert: v => v, secondary: true },
        ],
        unitFn: () => 'm',
    },
    lluvia: {
        title: 'Precipitacion - proximas 48h',
        series: [
            { key: 'prob_precipitacion', label: 'Probabilidad %', color: '#3b82f6', convert: v => v },
            { key: 'precipitacion', label: 'Cantidad (mm)', color: '#06b6d4', convert: v => v, secondary: true },
        ],
        unitFn: () => '%',
    },
    presion: {
        title: 'Presion atmosferica - proximas 48h',
        series: [
            { key: 'presion', label: 'Presion (hPa)', color: '#8b5cf6', convert: v => v },
        ],
        unitFn: () => 'hPa',
    },
    visibilidad: {
        title: 'Visibilidad - proximas 48h',
        series: [
            { key: 'visibilidad', label: 'Visibilidad (km)', color: '#06b6d4', convert: v => v != null ? v / 1000 : null },
        ],
        unitFn: () => 'km',
    },
    nubosidad: {
        title: 'Nubosidad - proximas 48h',
        series: [
            { key: 'nubosidad', label: 'Cobertura nubes %', color: '#8b5cf6', convert: v => v },
            { key: 'prob_precipitacion', label: 'Prob. lluvia %', color: '#3b82f6', convert: v => v, dashed: true },
        ],
        unitFn: () => '%',
    },
    temperatura: {
        title: 'Temperatura - proximas 48h',
        series: [
            { key: 'temperatura', label: 'Temperatura aire', color: '#ef4444', convert: v => v },
            { key: 'temp_agua', label: 'Temperatura agua', color: '#06b6d4', convert: v => v },
            { key: 'humedad', label: 'Humedad %', color: '#8b5cf6', convert: v => v, secondary: true },
        ],
        unitFn: () => 'C',
    },
};

window.toggleChart = function(type) {
    const panel = document.getElementById('chartPanel');
    document.querySelectorAll('.data-card.clickable').forEach(c => c.classList.remove('active'));

    if (!type || type === activeChart) {
        panel.classList.remove('open');
        activeChart = null;
        return;
    }

    activeChart = type;
    panel.classList.add('open');

    const cardMap = { viento: 'cardViento', oleaje: 'cardOleaje', lluvia: 'cardLluvia', visibilidad: 'cardVisibilidad', nubosidad: 'cardNubes', temperatura: 'cardTemp', presion: 'cardPresion' };
    const card = document.getElementById(cardMap[type]);
    if (card) card.classList.add('active');

    drawDetailChart(type);
    // Scroll al panel para que se vea
    setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 50);
};

function drawDetailChart(type) {
    const config = CHART_CONFIG[type];
    if (!config) return;

    document.getElementById('chartPanelTitle').textContent = config.title;

    const now = new Date();
    const hours48 = forecastData.filter(f => {
        const t = new Date(f.timestamp);
        return t >= new Date(now.getFullYear(), now.getMonth(), now.getDate()) && t <= new Date(now.getTime() + 48 * 3600 * 1000);
    });

    if (hours48.length === 0) return;

    const canvas = document.getElementById('detailChart');
    const ctx = canvas.getContext('2d');

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.clearRect(0, 0, W, H);

    const hasSecondary = config.series.some(s => s.secondary);
    const pad = { top: 20, right: hasSecondary ? 40 : 12, bottom: 32, left: 45 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    const primarySeries = config.series.filter(s => !s.secondary);
    const secondarySeries = config.series.filter(s => s.secondary);

    function getRange(seriesList) {
        let min = Infinity, max = -Infinity;
        for (const s of seriesList) {
            for (const h of hours48) {
                const v = s.convert(h[s.key]);
                if (v != null && isFinite(v)) {
                    min = Math.min(min, v);
                    max = Math.max(max, v);
                }
            }
        }
        if (min === Infinity) { min = 0; max = 10; }
        const margin = (max - min) * 0.1 || 1;
        return { min: Math.max(0, min - margin), max: max + margin };
    }

    const pRange = getRange(primarySeries);

    // ─── Bandas alternas por dia ────
    let prevDate = '';
    let dayColorIdx = 0;
    for (let i = 0; i < hours48.length; i++) {
        const dateStr = hours48[i].timestamp.slice(0, 10);
        if (dateStr !== prevDate) {
            // Encontrar donde termina este dia
            let endIdx = hours48.length - 1;
            for (let j = i + 1; j < hours48.length; j++) {
                if (hours48[j].timestamp.slice(0, 10) !== dateStr) { endIdx = j - 1; break; }
            }
            const x0 = Math.max(pad.left + (i / (hours48.length - 1)) * plotW, pad.left);
            const x1 = Math.min(pad.left + (endIdx / (hours48.length - 1)) * plotW, pad.left + plotW);

            // Fondo alterno
            if (dayColorIdx % 2 === 1) {
                ctx.fillStyle = 'rgba(255,255,255,0.03)';
                ctx.fillRect(x0, pad.top, x1 - x0, plotH);
            }

            // Separador y etiqueta de dia
            if (i > 0) {
                ctx.strokeStyle = '#ffffff18';
                ctx.lineWidth = 1;
                ctx.beginPath(); ctx.moveTo(x0, pad.top); ctx.lineTo(x0, pad.top + plotH); ctx.stroke();
            }
            // Etiqueta de dia centrada
            const DAY_SHORT_CHART = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab'];
            const d = new Date(dateStr + 'T12:00:00');
            const dayLabel = DAY_SHORT_CHART[d.getDay()] + ' ' + d.getDate();
            ctx.fillStyle = '#ffffff30';
            ctx.font = '10px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(dayLabel, x0 + 4, pad.top + 12);

            prevDate = dateStr;
            dayColorIdx++;
        }
    }

    // Grid
    ctx.strokeStyle = '#1e3050';
    ctx.lineWidth = 0.5;
    const gridLines = 5;
    for (let i = 0; i <= gridLines; i++) {
        const y = pad.top + (plotH / gridLines) * i;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + plotW, y);
        ctx.stroke();
        const val = pRange.max - ((pRange.max - pRange.min) / gridLines) * i;
        ctx.fillStyle = '#8895a7';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(Math.round(val * 10) / 10, pad.left - 6, y + 4);
    }

    // Time labels
    ctx.fillStyle = '#8895a7';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(hours48.length / 12));
    for (let i = 0; i < hours48.length; i += step) {
        const x = pad.left + (i / (hours48.length - 1)) * plotW;
        const t = hours48[i].timestamp;
        ctx.fillText(t.slice(11, 16), x, H - pad.bottom + 14);
    }

    // "Ahora" line
    const nowIdx = hours48.findIndex(f => new Date(f.timestamp) >= now);
    if (nowIdx > 0) {
        const xNow = pad.left + (nowIdx / (hours48.length - 1)) * plotW;
        ctx.strokeStyle = '#ffffff30';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(xNow, pad.top);
        ctx.lineTo(xNow, pad.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#ffffff60';
        ctx.font = '10px -apple-system, sans-serif';
        ctx.fillText('ahora', xNow, pad.top - 5);
    }

    function drawLine(series, range) {
        const values = hours48.map(h => series.convert(h[series.key]));
        ctx.strokeStyle = series.color;
        ctx.lineWidth = 2;
        if (series.dashed) ctx.setLineDash([6, 3]);
        else ctx.setLineDash([]);

        ctx.beginPath();
        let started = false;
        for (let i = 0; i < values.length; i++) {
            const v = values[i];
            if (v == null) continue;
            const x = pad.left + (i / (values.length - 1)) * plotW;
            const y = pad.top + plotH - ((v - range.min) / (range.max - range.min)) * plotH;
            if (!started) { ctx.moveTo(x, y); started = true; }
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.setLineDash([]);

        // Area fill para serie principal
        if (!series.dashed && !series.secondary) {
            ctx.globalAlpha = 0.08;
            ctx.fillStyle = series.color;
            ctx.beginPath();
            started = false;
            let lastX = pad.left;
            for (let i = 0; i < values.length; i++) {
                const v = values[i];
                if (v == null) continue;
                const x = pad.left + (i / (values.length - 1)) * plotW;
                const y = pad.top + plotH - ((v - range.min) / (range.max - range.min)) * plotH;
                if (!started) { ctx.moveTo(x, y); started = true; }
                else ctx.lineTo(x, y);
                lastX = x;
            }
            ctx.lineTo(lastX, pad.top + plotH);
            ctx.lineTo(pad.left, pad.top + plotH);
            ctx.closePath();
            ctx.fill();
            ctx.globalAlpha = 1;
        }
    }

    for (const s of primarySeries) drawLine(s, pRange);

    if (secondarySeries.length > 0) {
        const sRange = getRange(secondarySeries);
        for (const s of secondarySeries) {
            ctx.globalAlpha = 0.5;
            drawLine(s, sRange);
            ctx.globalAlpha = 1;
        }
        // Eje secundario a la derecha
        ctx.fillStyle = '#8895a780';
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'left';
        const sGridLines = 4;
        for (let i = 0; i <= sGridLines; i++) {
            const val = sRange.max - ((sRange.max - sRange.min) / sGridLines) * i;
            const y = pad.top + (plotH / sGridLines) * i;
            ctx.fillText(Math.round(val * 10) / 10, pad.left + plotW + 4, y + 4);
        }
    }

    // Legend
    document.getElementById('chartLegend').innerHTML = config.series.map(s =>
        `<div class="chart-legend-item">
            <div class="chart-legend-dot" style="background:${s.color};${s.dashed ? 'background:transparent;border-top:2px dashed ' + s.color + ';height:0' : ''}"></div>
            <span>${s.label}${s.secondary ? ' (eje secundario)' : ''}</span>
        </div>`
    ).join('');
}

window.addEventListener('resize', () => {
    if (activeChart) drawDetailChart(activeChart);
});
