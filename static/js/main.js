const form = document.getElementById('downloadForm');
const urlInput = document.getElementById('urlInput');
const downloadBtn = document.getElementById('downloadBtn');
const pasteBtn = document.getElementById('pasteBtn');
const statusMsg = document.getElementById('statusMsg');
const headerBadge = document.getElementById('headerBadge');
const featQuality = document.getElementById('featQuality');

function getSelectedQuality() {
    const checked = form.querySelector('input[name="quality"]:checked');
    return checked ? checked.value : '192';
}

function syncQualityUI(val) {
    if (headerBadge) headerBadge.textContent = `${val}kbps • MP3`;
    if (featQuality) featQuality.textContent = `${val} kbps MP3`;
}

form.querySelectorAll('input[name="quality"]').forEach(radio => {
    radio.addEventListener('change', () => syncQualityUI(getSelectedQuality()));
});
syncQualityUI(getSelectedQuality());

pasteBtn.addEventListener('click', async () => {
    try {
        const text = await navigator.clipboard.readText();
        if (text.trim()) {
            urlInput.value = text.trim();
            urlInput.focus();
            pasteBtn.style.color = 'var(--accent)';
            setTimeout(() => (pasteBtn.style.color = ''), 600);
        }
    } catch {
        urlInput.focus();
    }
});

function isValidUrl(str) {
    try {
        const parsed = new URL(str);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
        return false;
    }
}

function extractFilename(contentDisposition, fallback) {
    if (!contentDisposition) return fallback;
    const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
        return decodeURIComponent(utf8Match[1]);
    }
    const asciiMatch = contentDisposition.match(/filename="?([^";\n]+)"?/i);
    if (asciiMatch && asciiMatch[1]) {
        return asciiMatch[1];
    }
    return fallback;
}

async function handleDownload() {
    const url = urlInput.value.trim();
    if (!url) return showStatus('Lütfen bir link girin.', 'error');
    if (!isValidUrl(url) || url.indexOf('http', 8) !== -1) {
        return showStatus('Geçersiz link. Linki iki kez yapıştırmadığınızdan emin olun.', 'error');
    }

    setLoading(true);
    hideStatus();

    try {
        const formData = new FormData(form);
        const response = await fetch('/download', {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || `Hata: ${response.status}`);
        }

        const blob = await response.blob();
        const filename = extractFilename(
            response.headers.get('Content-Disposition'),
            'ses.mp3'
        );

        const objectURL = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = objectURL;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(objectURL), 5000);

        showStatus(`✓ İndirme tamamlandı! ${getSelectedQuality()} kbps MP3 kaydedildi.`, 'success');
        urlInput.value = '';
    } catch (err) {
        showStatus('⚠ ' + (err.message || 'Bir hata oluştu, tekrar deneyin.'), 'error');
    } finally {
        setLoading(false);
    }
}

form.addEventListener('submit', (e) => {
    e.preventDefault();
    handleDownload();
});

function setLoading(state) {
    downloadBtn.disabled = state;
    downloadBtn.classList.toggle('loading', state);
}

function showStatus(message, type = 'error') {
    statusMsg.textContent = message;
    statusMsg.className = `status-msg ${type}`;
    statusMsg.hidden = false;
}

function hideStatus() {
    statusMsg.hidden = true;
}

urlInput.addEventListener('input', () => {
    if (!statusMsg.hidden) hideStatus();
});

const observer = new MutationObserver(() => {
    const fast = downloadBtn.disabled;
    document.querySelectorAll('.waveform span').forEach(bar => {
        const dur = parseFloat(getComputedStyle(bar).getPropertyValue('--dur') || 1);
        bar.style.animationDuration = fast ? `${dur * 0.35}s` : '';
    });
});
observer.observe(downloadBtn, { attributes: true, attributeFilter: ['disabled'] });

const params = new URLSearchParams(window.location.search);
const incomingQuality = params.get('quality');
if (incomingQuality) {
    const radio = form.querySelector(`input[name="quality"][value="${incomingQuality}"]`);
    if (radio) {
        radio.checked = true;
        syncQualityUI(incomingQuality);
    }
}
const incomingUrl = params.get('url');
if (incomingUrl) {
    urlInput.value = incomingUrl;
    if (params.get('auto') === '1') {
        handleDownload();
    }
}