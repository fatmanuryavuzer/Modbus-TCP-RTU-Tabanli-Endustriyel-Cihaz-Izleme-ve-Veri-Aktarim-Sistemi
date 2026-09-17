let allReadings = [];
let editingDeviceKey = null;
let editingDevice = null;
let deviceHealthByKey = {};
let activeStatusPopover = null;
let activeStatusAnchor = null;
let activeTable = "live";
let historyReadings = [];
let selectedTransferMethod = "ftp";
let managedDevices = [];
let selectedManagedDeviceKeys = new Set();
let activeRegisterEditor = null;
let deviceFormDirty = false;
let suppressDeviceFormDirty = false;


function markDeviceFormDirty() {
    if (!suppressDeviceFormDirty) {
        deviceFormDirty = true;
    }
}


function confirmDiscardDeviceChanges() {
    if (!deviceFormDirty) {
        return true;
    }

    return window.confirm(
        "Kaydedilmemiş değişiklikler var. Çıkmak istediğinize emin misiniz?"
    );
}


function getFilterValues() {
    return {
        deviceKey: document.getElementById(
            "device-filter"
        ).value,
        measurementKey: document.getElementById(
            "measurement-filter"
        ).value,
        startDate: document.getElementById(
            "start-date"
        ).value,
        endDate: document.getElementById(
            "end-date"
        ).value
    };
}


function getFilteredTableReadings() {
    const {
        deviceKey,
        measurementKey
    } = getFilterValues();

    return allReadings.filter((reading) => {
        const matchesDevice =
            !deviceKey
            || reading.device_key === deviceKey;

        const matchesMeasurement =
            !measurementKey
            || reading.measurement_key === measurementKey;

        return matchesDevice && matchesMeasurement;
    });
}


function explainReadingError(rawError) {
    const technical = String(
        rawError || "Hata nedeni belirtilmedi."
    ).trim();
    const normalized = technical.toLocaleLowerCase("tr-TR");

    if (
        normalized.includes("timed out")
        || normalized.includes("timeout")
        || normalized.includes("zaman aşımı")
    ) {
        return {
            summary: "Cihaz zamanında cevap vermedi.",
            suggestion: "Cihazın açık olduğunu, host/COM port ve bağlantı ayarlarını kontrol edin.",
            technical
        };
    }

    if (
        normalized.includes("connection refused")
        || normalized.includes("actively refused")
        || normalized.includes("bağlantı reddedildi")
    ) {
        return {
            summary: "Cihaz bağlantıyı reddetti.",
            suggestion: "TCP server veya simülatörün çalıştığını ve port numarasının doğru olduğunu kontrol edin.",
            technical
        };
    }

    if (
        normalized.includes("name or service not known")
        || normalized.includes("nodename nor servname")
        || normalized.includes("getaddrinfo")
        || normalized.includes("no route to host")
    ) {
        return {
            summary: "Cihaz adresine ulaşılamadı.",
            suggestion: "Host/IP adresini ve aynı ağda olduğunuzu kontrol edin.",
            technical
        };
    }

    if (
        normalized.includes("unit id")
        || normalized.includes("slave id")
    ) {
        return {
            summary: "Unit ID eşleşmedi.",
            suggestion: "Cihazdaki gerçek slave adresini ve projedeki Unit ID değerini karşılaştırın.",
            technical
        };
    }

    if (normalized.includes("crc")) {
        return {
            summary: "RTU paket doğrulaması başarısız.",
            suggestion: "Baudrate, parity, stopbits, bytesize ve kablo bağlantısını kontrol edin.",
            technical
        };
    }

    if (normalized.includes("yeni register tanımından ilk okuma bekleniyor")) {
        return {
            summary: "Yeni register tanımı için ilk okuma bekleniyor.",
            suggestion: "Polling turunun tamamlanmasını bekleyin; yeni değer bir sonraki okumada gelecektir.",
            technical
        };
    }

    if (
        normalized.includes("function code")
        || normalized.includes("register")
        || normalized.includes("adres")
    ) {
        return {
            summary: "Register okuma tanımı cihazla uyuşmuyor.",
            suggestion: "Function Code, register adresi, register adedi ve veri tipini cihaz dokümanından kontrol edin.",
            technical
        };
    }

    if (
        normalized.includes("pyserial")
        || normalized.includes("no module named 'serial'")
    ) {
        return {
            summary: "RTU seri haberleşme paketi eksik.",
            suggestion: "Gerçek COM port kullanılıyorsa pyserial paketinin kurulu olduğunu kontrol edin.",
            technical
        };
    }

    return {
        summary: "Ölçüm okunamadı.",
        suggestion: "Cihaz bağlantısını ve ölçüm tanımındaki adres bilgilerini kontrol edin.",
        technical
    };
}


function createStatusBadge(reading) {
    const normalizedStatus = reading.status || "HATA";
    const isError = normalizedStatus !== "OK";
    const badge = document.createElement(
        isError ? "button" : "span"
    );

    badge.className = normalizedStatus === "OK"
        ? "status-badge status-ok"
        : "status-badge status-error";

    if (isError) {
        badge.type = "button";
        badge.classList.add("status-details-trigger");
        badge.title =
            "Hata ayrıntılarını ve çözüm önerisini görmek için tıklayın";
        badge.setAttribute(
            "aria-label",
            "Hata ayrıntılarını göster"
        );
    }

    badge.dataset.status = normalizedStatus;
    badge.dataset.deviceName = reading.device_name || "-";
    badge.dataset.measurementName =
        reading.measurement_name || "-";
    badge.dataset.protocol = reading.protocol || "tcp";
    badge.dataset.unitId = reading.unit_id ?? "-";
    badge.dataset.address = reading.address ?? "-";
    badge.dataset.timestamp = reading.timestamp || "-";
    badge.dataset.error = reading.error
        || "Hata nedeni belirtilmedi.";

    const icon = document.createElement("span");
    icon.className = "status-icon";
    icon.textContent = normalizedStatus === "OK" ? "✓" : "✕";

    const label = document.createElement("span");
    label.textContent = normalizedStatus;

    badge.append(
        icon,
        label
    );

    return badge;
}


function closeStatusDetails() {
    if (activeStatusPopover) {
        activeStatusPopover.remove();
    }

    activeStatusPopover = null;
    activeStatusAnchor = null;
}


function createStatusDetailRow(label, value, extraClass = "") {
    const row = document.createElement("div");
    row.className = "status-popover-row";

    const labelElement = document.createElement("span");
    labelElement.className = "status-popover-label";
    labelElement.textContent = label;

    const valueElement = document.createElement("span");
    valueElement.className =
        `status-popover-value ${extraClass}`.trim();
    valueElement.textContent = value || "-";

    row.append(
        labelElement,
        valueElement
    );

    return row;
}


function showStatusDetails(anchor) {
    closeStatusDetails();

    const popover = document.createElement("section");
    popover.className = "status-popover";
    popover.setAttribute("role", "dialog");
    popover.setAttribute(
        "aria-label",
        "Hata ayrıntısı"
    );

    const header = document.createElement("div");
    header.className = "status-popover-header";

    const title = document.createElement("h3");
    title.className = "status-popover-title";
    title.textContent = "Hata ve önerilen kontrol";

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "status-popover-close";
    closeButton.textContent = "×";
    closeButton.setAttribute("aria-label", "Kapat");
    closeButton.addEventListener(
        "click",
        closeStatusDetails
    );

    header.append(
        title,
        closeButton
    );
    popover.appendChild(header);

    const explanation = explainReadingError(
        anchor.dataset.error
    );
    const details = [
        ["Durum", anchor.dataset.status],
        ["Cihaz", anchor.dataset.deviceName],
        ["Ölçüm", anchor.dataset.measurementName],
        ["Protokol", anchor.dataset.protocol.toUpperCase()],
        ["Unit ID", anchor.dataset.unitId],
        ["Register adresi", anchor.dataset.address],
        ["Son güncelleme", formatTimestamp(anchor.dataset.timestamp)],
        ["Hata özeti", explanation.summary, "status-popover-error"],
        ["Önerilen kontrol", explanation.suggestion, "status-popover-suggestion"],
        ["Teknik ayrıntı", explanation.technical, "status-popover-technical"]
    ];

    for (const [label, value, extraClass] of details) {
        popover.appendChild(
            createStatusDetailRow(
                label,
                value,
                extraClass
            )
        );
    }

    document.body.appendChild(popover);

    const anchorRect = anchor.getBoundingClientRect();
    const popoverWidth = Math.min(
        320,
        window.innerWidth - 24
    );

    popover.style.width = `${popoverWidth}px`;

    const left = Math.max(
        12,
        Math.min(
            anchorRect.left,
            window.innerWidth - popoverWidth - 12
        )
    );

    let top = anchorRect.bottom + 8;

    if (
        top + popover.offsetHeight
        > window.innerHeight - 12
    ) {
        top = anchorRect.top - popover.offsetHeight - 8;
    }

    popover.style.left = `${left}px`;
    popover.style.top = `${Math.max(12, top)}px`;

    activeStatusPopover = popover;
    activeStatusAnchor = anchor;
}


function setupStatusDetails() {
    const tableBody = document.getElementById(
        "readings-table-body"
    );

    tableBody.addEventListener(
        "click",
        (event) => {
            const trigger = event.target.closest(
                ".status-details-trigger"
            );

            if (!trigger) {
                return;
            }

            event.stopPropagation();

            if (activeStatusAnchor === trigger) {
                closeStatusDetails();
                return;
            }

            showStatusDetails(trigger);
        }
    );

    document.addEventListener(
        "click",
        (event) => {
            if (!activeStatusPopover) {
                return;
            }

            if (activeStatusPopover.contains(event.target)) {
                return;
            }

            if (
                event.target.closest(
                    ".status-details-trigger"
                )
            ) {
                return;
            }

            closeStatusDetails();
        }
    );

    document.addEventListener(
        "keydown",
        (event) => {
            if (event.key === "Escape") {
                closeStatusDetails();
            }
        }
    );

    window.addEventListener(
        "resize",
        closeStatusDetails
    );
}


function createInfoCell(primaryText, secondaryText) {
    const cell = document.createElement("td");

    const primary = document.createElement("div");
    primary.className = "cell-primary";
    primary.textContent = primaryText || "-";

    const secondary = document.createElement("div");
    secondary.className = "cell-secondary";
    secondary.textContent = secondaryText || "-";

    cell.append(
        primary,
        secondary
    );

    return cell;
}


function createRegisterEditButton(reading, cell) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "register-edit-button";
    button.textContent = "Düzenle";
    button.title = "Register adresi ve adedini düzenle";
    button.addEventListener(
        "click",
        () => startRegisterEdit(cell, reading)
    );

    return button;
}


function startRegisterEdit(cell, reading) {
    activeRegisterEditor = {
        reading
    };
    cell.replaceChildren();

    const editor = document.createElement("div");
    editor.className = "register-edit-form";

    const addressLabel = document.createElement("label");
    addressLabel.textContent = "Adres";
    const addressInput = document.createElement("input");
    addressInput.type = "number";
    addressInput.min = "0";
    addressInput.max = "65535";
    addressInput.value = reading.address ?? "";
    addressLabel.appendChild(addressInput);

    const countLabel = document.createElement("label");
    countLabel.textContent = "Adet";
    const countInput = document.createElement("input");
    countInput.type = "number";
    countInput.min = "1";
    countInput.max = "125";
    countInput.value = reading.count ?? "";
    countLabel.appendChild(countInput);

    const feedback = document.createElement("small");
    feedback.className = "register-edit-feedback";

    const actions = document.createElement("div");
    actions.className = "register-edit-actions";

    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.className = "register-edit-save";
    saveButton.textContent = "Kaydet";

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "register-edit-cancel";
    cancelButton.textContent = "İptal";

    cancelButton.addEventListener(
        "click",
        () => {
            activeRegisterEditor = null;
            renderTable();
        }
    );

    saveButton.addEventListener(
        "click",
        async () => {
            const address = Number(addressInput.value);
            const count = Number(countInput.value);
            const dataType = String(
                reading.data_type || ""
            ).toLowerCase();

            if (
                !Number.isInteger(address)
                || address < 0
                || address > 65535
            ) {
                feedback.textContent =
                    "Adres 0 ile 65535 arasında olmalı.";
                return;
            }

            if (
                !Number.isInteger(count)
                || count < 1
                || count > 125
            ) {
                feedback.textContent =
                    "Adet 1 ile 125 arasında olmalı.";
                return;
            }

            if (address + count > 65536) {
                feedback.textContent =
                    "Register aralığı 65535 adresini aşamaz.";
                return;
            }

            if (dataType === "u32" && count !== 2) {
                feedback.textContent =
                    "U32 veri tipi için adet 2 olmalı.";
                return;
            }

            saveButton.disabled = true;
            cancelButton.disabled = true;
            saveButton.textContent = "Kaydediliyor...";
            feedback.textContent = "";

            try {
                const response = await fetch(
                    `/api/devices/${encodeURIComponent(
                        reading.device_key
                    )}/measurements/${encodeURIComponent(
                        reading.measurement_key
                    )}`,
                    {
                        method: "PATCH",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            address,
                            count
                        })
                    }
                );
                const result = await response.json();

                if (!response.ok) {
                    throw new Error(
                        result.error || "Register bilgisi güncellenemedi."
                    );
                }

                activeRegisterEditor = null;
                reading.address = address;
                reading.count = count;
                renderTable();

                try {
                    await refreshReadings();
                } catch (refreshError) {
                    console.error(
                        "Yeni register okuması bekleniyor:",
                        refreshError
                    );
                }
            } catch (error) {
                feedback.textContent = error.message;
                saveButton.disabled = false;
                cancelButton.disabled = false;
                saveButton.textContent = "Kaydet";
            }
        }
    );

    actions.append(
        saveButton,
        cancelButton
    );
    editor.append(
        addressLabel,
        countLabel,
        actions,
        feedback
    );
    cell.appendChild(editor);
    addressInput.focus();
    addressInput.select();
}


function normalizeDeviceHealthStatus(status) {
    const knownStatuses = [
        "ONLINE",
        "DEGRADED",
        "OFFLINE",
        "UNKNOWN",
        "DISABLED"
    ];

    return knownStatuses.includes(status)
        ? status
        : "UNKNOWN";
}


function createDeviceCell(reading) {
    const cell = document.createElement("td");

    const primary = document.createElement("div");
    primary.className = "cell-primary";
    primary.textContent = reading.device_name || "-";

    const secondary = document.createElement("div");
    secondary.className = "cell-secondary";
    secondary.textContent = reading.device_key || "-";

    const health = deviceHealthByKey[reading.device_key];
    const status = normalizeDeviceHealthStatus(
        health?.status
    );

    const labels = {
        ONLINE: "ÇEVRİMİÇİ",
        DEGRADED: "KISMİ SORUN",
        OFFLINE: "ÇEVRİMDIŞI",
        UNKNOWN: "BİLİNMİYOR",
        DISABLED: "DEVRE DIŞI"
    };

    const healthLabel = document.createElement("div");
    healthLabel.className =
        `device-health-label device-health-${status.toLowerCase()}`;

    const dot = document.createElement("span");
    dot.className = "device-health-dot";

    const label = document.createElement("span");
    label.textContent = labels[status];

    healthLabel.append(
        dot,
        label
    );

    cell.append(
        primary,
        secondary,
        healthLabel
    );

    return cell;
}


function createProtocolBadge(protocol) {
    const badge = document.createElement("span");
    const normalizedProtocol = String(
        protocol || "tcp"
    ).toLowerCase();

    badge.className = normalizedProtocol === "rtu"
        ? "protocol-badge protocol-rtu"
        : "protocol-badge protocol-tcp";

    badge.textContent = normalizedProtocol.toUpperCase();

    return badge;
}


function formatReadingValue(reading) {
    if (reading.status !== "OK") {
        return "Okunamadı";
    }

    const numericValue = Number(reading.value);
    const value = Number.isFinite(numericValue)
        ? numericValue.toFixed(1)
        : reading.value ?? "-";

    return `${value} ${reading.unit || ""}`.trim();
}


function formatTimestamp(timestamp) {
    return String(timestamp || "-").replace("T", " ");
}


function getTimestampAgeSeconds(timestamp) {
    const timestampDate = new Date(timestamp);

    if (Number.isNaN(timestampDate.getTime())) {
        return null;
    }

    return Math.max(
        0,
        (Date.now() - timestampDate.getTime()) / 1000
    );
}


function formatRelativeAge(timestamp) {
    const ageInSeconds = getTimestampAgeSeconds(timestamp);

    if (ageInSeconds === null) {
        return "Güncelleme bilinmiyor";
    }

    if (ageInSeconds < 5) {
        return "Şimdi";
    }

    if (ageInSeconds < 60) {
        return `${Math.floor(ageInSeconds)} sn önce`;
    }

    const ageInMinutes = Math.floor(ageInSeconds / 60);

    if (ageInMinutes < 60) {
        return `${ageInMinutes} dk önce`;
    }

    const ageInHours = Math.floor(ageInMinutes / 60);
    const remainingMinutes = ageInMinutes % 60;

    return remainingMinutes
        ? `${ageInHours} sa ${remainingMinutes} dk önce`
        : `${ageInHours} sa önce`;
}


function getFreshnessClass(timestamp) {
    const ageInSeconds = getTimestampAgeSeconds(timestamp);

    if (ageInSeconds === null) {
        return "is-unknown";
    }

    if (ageInSeconds <= 10) {
        return "is-fresh";
    }

    if (ageInSeconds <= 15) {
        return "is-aging";
    }

    return "is-stale";
}


function createFreshnessCell(timestamp) {
    const cell = document.createElement("td");
    cell.className = "reading-timestamp";

    const freshness = document.createElement("div");
    freshness.className = `reading-freshness ${getFreshnessClass(
        timestamp
    )}`;
    freshness.textContent = formatRelativeAge(timestamp);

    const exactTimestamp = document.createElement("div");
    exactTimestamp.className = "cell-secondary";
    exactTimestamp.textContent = formatTimestamp(timestamp);

    cell.title = `Tam zaman: ${formatTimestamp(timestamp)}`;
    cell.append(
        freshness,
        exactTimestamp
    );

    return cell;
}


function updateDownloadLink() {
    const downloadButton = document.getElementById(
        "download-filtered-csv"
    );

    const {
        deviceKey,
        measurementKey,
        startDate,
        endDate
    } = getFilterValues();

    const format = document.getElementById(
    "transfer-format"
).value;

const downloadPath = format === "json"
    ? "/download/json"
    : "/download/csv";

    const parameters = new URLSearchParams();

    if (deviceKey) {
        parameters.set(
            "device_key",
            deviceKey
        );
    }

    if (measurementKey) {
        parameters.set(
            "measurement_key",
            measurementKey
        );
    }

    if (startDate) {
        parameters.set(
            "start_date",
            startDate
        );
    }

    if (endDate) {
        parameters.set(
            "end_date",
            endDate
        );
    }

    const queryString = parameters.toString();

    downloadButton.href = queryString
       ? `${downloadPath}?${queryString}`
    :  downloadPath;

    downloadButton.textContent =
       format === "json"
         ? "Filtreli JSON İndir"
         : "Filtreli CSV İndir";
}


function renderTable() {
    const tableBody = document.getElementById(
        "readings-table-body"
    );

    if (activeRegisterEditor) {
        return;
    }

    const filteredReadings = getFilteredTableReadings();

    tableBody.innerHTML = "";

    if (filteredReadings.length === 0) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");

        cell.colSpan = 7;
        cell.className = "empty-row";
        cell.textContent =
            "Filtreye uygun kayıt bulunamadı.";

        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }

    for (const reading of filteredReadings) {
        const row = document.createElement("tr");

        const deviceCell = createDeviceCell(reading);

        const measurementCell = createInfoCell(
            reading.measurement_name,
            reading.measurement_key
        );

        const registerCell = createInfoCell(
            reading.address ?? "-",
            `Unit ID: ${reading.unit_id ?? "-"} · Adet: ${reading.count ?? "-"}`
        );
        registerCell.classList.add("table-register-cell");
        registerCell.appendChild(
            createRegisterEditButton(
                reading,
                registerCell
            )
        );

        const valueCell = document.createElement("td");
        valueCell.textContent = formatReadingValue(reading);

        const protocolCell = document.createElement("td");
        protocolCell.appendChild(
            createProtocolBadge(reading.protocol)
        );

        const timestampCell = createFreshnessCell(
            reading.timestamp
        );

        const statusCell = document.createElement("td");

        statusCell.appendChild(
            createStatusBadge(reading)
        );

        row.append(
            deviceCell,
            measurementCell,
            registerCell,
            valueCell,
            protocolCell,
            timestampCell,
            statusCell
        );

        tableBody.appendChild(row);
    }
}


function renderHistoryTable() {
    const tableBody = document.getElementById(
        "history-table-body"
    );

    tableBody.innerHTML = "";

    if (historyReadings.length === 0) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");

        cell.colSpan = 7;
        cell.className = "empty-row";
        cell.textContent =
            "Filtreye uygun geçmiş kayıt bulunamadı.";

        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }

    for (const reading of historyReadings) {
        const row = document.createElement("tr");

        const deviceCell = createDeviceCell(reading);

        const measurementCell = createInfoCell(
            reading.measurement_name,
            reading.measurement_key
        );

        const registerCell = createInfoCell(
            reading.address ?? "-",
            `Unit ID: ${reading.unit_id ?? "-"}`
        );

        const valueCell = document.createElement("td");
        valueCell.textContent = formatReadingValue(reading);

        const protocolCell = document.createElement("td");
        protocolCell.appendChild(
            createProtocolBadge(reading.protocol)
        );

        const timestampCell = document.createElement("td");
        timestampCell.className = "reading-timestamp";
        timestampCell.textContent = formatTimestamp(
            reading.timestamp
        );

        const statusCell = document.createElement("td");
        statusCell.appendChild(
            createStatusBadge(reading)
        );

        row.append(
            deviceCell,
            measurementCell,
            registerCell,
            valueCell,
            protocolCell,
            timestampCell,
            statusCell
        );

        tableBody.appendChild(row);
    }
}


function updateSummary(readings) {
    const activeDevices = new Set(
        readings
            .filter((reading) => reading.status === "OK")
            .map((reading) => reading.device_key)
    ).size;

    const successfulReadings = readings.filter(
        (reading) => reading.status === "OK"
    ).length;

    const errorReadings = readings.filter(
        (reading) => reading.status !== "OK"
    ).length;

    document.getElementById(
        "active-devices"
    ).textContent = activeDevices;

    document.getElementById(
        "total-readings"
    ).textContent = readings.length;

    document.getElementById(
        "successful-readings"
    ).textContent = successfulReadings;

    document.getElementById(
        "error-readings"
    ).textContent = errorReadings;
}


function updateDeviceHealth(health) {
    deviceHealthByKey = Object.fromEntries(
        health.map((device) => [
            device.device_key,
            {
                ...device,
                status: normalizeDeviceHealthStatus(
                    device.status
                )
            }
        ])
    );

    const onlineDeviceCount = health.filter(
        (device) => normalizeDeviceHealthStatus(
            device.status
        ) === "ONLINE"
    ).length;

    document.getElementById(
        "active-devices"
    ).textContent = onlineDeviceCount;

    renderTable();
}


function updateConnectionStatus(readings, health) {
    const lastUpdate = document.getElementById(
        "last-update"
    );

    const connectionStatus = document.getElementById(
        "connection-status"
    );

    if (readings.length === 0) {
        lastUpdate.textContent =
            "Son güncelleme: Veri yok";
        lastUpdate.removeAttribute("title");

        connectionStatus.textContent =
            "Bağlantı durumu: Veri yok";

        connectionStatus.className =
            "connection-status status-error";

        return;
    }

    const latestReading = readings.reduce(
        (latest, reading) => {
            if (!latest) {
                return reading;
            }

            const latestTime = new Date(
                latest.timestamp
            ).getTime();
            const readingTime = new Date(
                reading.timestamp
            ).getTime();

            return readingTime > latestTime
                ? reading
                : latest;
        },
        null
    );
    const latestTimestamp = latestReading?.timestamp;
    const ageInSeconds = getTimestampAgeSeconds(
        latestTimestamp
    );

    const isStale =
        ageInSeconds === null
        || ageInSeconds > 15;

    lastUpdate.textContent =
        `Son güncelleme: ${formatRelativeAge(latestTimestamp)}`;
    lastUpdate.title =
        `Tam zaman: ${formatTimestamp(latestTimestamp)}`;

    if (isStale) {
        connectionStatus.textContent =
            "Bağlantı durumu: VERİ GECİKMESİ";

        connectionStatus.className =
            "connection-status status-error";

        return;
    }

    const healthRecords = health || [];

    if (!healthRecords.length) {
        const hasErrors = readings.some(
            (reading) => reading.status !== "OK"
        );

        connectionStatus.textContent = hasErrors
            ? "Bağlantı durumu: HATA"
            : "Bağlantı durumu: OK";
        connectionStatus.className = hasErrors
            ? "connection-status status-error"
            : "connection-status status-ok";
        return;
    }

    const activeDevices = healthRecords.filter(
        (device) => device.status !== "DISABLED"
    );
    const onlineDevices = activeDevices.filter(
        (device) => device.status === "ONLINE"
    );

    if (!activeDevices.length) {
        connectionStatus.textContent =
            "Bağlantı durumu: AKTİF CİHAZ YOK";

        connectionStatus.className =
            "connection-status status-warning";

    } else if (onlineDevices.length === activeDevices.length) {
        connectionStatus.textContent =
            "Bağlantı durumu: OK";

        connectionStatus.className =
            "connection-status status-ok";

    } else if (onlineDevices.length > 0) {
        connectionStatus.textContent =
            "Bağlantı durumu: KISMİ SORUN";

        connectionStatus.className =
            "connection-status status-warning";

    } else {
        connectionStatus.textContent =
            "Bağlantı durumu: HATA";

        connectionStatus.className =
            "connection-status status-error";

    }
}


async function loadReadings() {
    const response = await fetch("/api/readings");

    if (!response.ok) {
        throw new Error("API isteği başarısız.");
    }

    allReadings = await response.json();

    updateSummary(allReadings);
    renderTable();
    updateDownloadLink();
}


async function loadHistory() {
    const {
        deviceKey,
        measurementKey,
        startDate,
        endDate
    } = getFilterValues();

    const parameters = new URLSearchParams();

    if (deviceKey) {
        parameters.set(
            "device_key",
            deviceKey
        );
    }

    if (measurementKey) {
        parameters.set(
            "measurement_key",
            measurementKey
        );
    }

    if (startDate) {
        parameters.set(
            "start_date",
            startDate
        );
    }

    if (endDate) {
        parameters.set(
            "end_date",
            endDate
        );
    }

    parameters.set(
        "limit",
        "100"
    );

    const response = await fetch(
        `/api/history?${parameters.toString()}`
    );

    if (!response.ok) {
        throw new Error(
            "Geçmiş kayıt API isteği başarısız."
        );
    }

    historyReadings = await response.json();
    renderHistoryTable();
}


async function loadHealth() {
    const response = await fetch("/api/health");

    if (!response.ok) {
        throw new Error("Sağlık API isteği başarısız.");
    }

    const health = await response.json();

    updateDeviceHealth(health);
}


async function refreshReadings() {
    const connectionStatus = document.getElementById(
        "connection-status"
    );
    let readingsLoaded = false;

    try {
        await loadReadings();
        readingsLoaded = true;
    } catch (error) {
        connectionStatus.textContent =
            "Bağlantı durumu: API erişilemiyor";

        connectionStatus.className =
            "connection-status status-error";

        console.error(
            "Okumalar yüklenemedi:",
            error
        );
    }

    try {
        await loadHealth();
    } catch (error) {
        console.error(
            "Cihaz sağlıkları yüklenemedi:",
            error
        );
    }

    if (readingsLoaded) {
        updateConnectionStatus(
            allReadings,
            Object.values(deviceHealthByKey)
        );
    }

    if (activeTable === "history") {
        try {
            await loadHistory();
        } catch (error) {
            console.error(
                "Geçmiş kayıtlar yüklenemedi:",
                error
            );
        }
    }
}


function setActiveTable(tableName) {
    const liveTab = document.getElementById(
        "live-table-tab"
    );
    const historyTab = document.getElementById(
        "history-table-tab"
    );
    const livePanel = document.getElementById(
        "live-table-panel"
    );
    const historyPanel = document.getElementById(
        "history-table-panel"
    );
    const eyebrow = document.getElementById(
        "table-panel-eyebrow"
    );
    const title = document.getElementById(
        "table-panel-title"
    );

    activeTable = tableName;

    const isHistory = tableName === "history";

    liveTab.classList.toggle(
        "is-active",
        !isHistory
    );
    historyTab.classList.toggle(
        "is-active",
        isHistory
    );

    liveTab.setAttribute(
        "aria-selected",
        String(!isHistory)
    );
    historyTab.setAttribute(
        "aria-selected",
        String(isHistory)
    );

    livePanel.hidden = isHistory;
    historyPanel.hidden = !isHistory;

    eyebrow.textContent = isHistory
        ? "GEÇMİŞ KAYITLAR"
        : "CANLI VERİ";
    title.textContent = isHistory
        ? "Geçmiş ölçüm tablosu"
        : "Ölçüm tablosu";

    if (isHistory) {
        loadHistory().catch((error) => {
            console.error(
                "Geçmiş kayıtlar yüklenemedi:",
                error
            );
        });
    }
}


function setupTableTabs() {
    document.getElementById(
        "live-table-tab"
    ).addEventListener(
        "click",
        () => setActiveTable("live")
    );

    document.getElementById(
        "history-table-tab"
    ).addEventListener(
        "click",
        () => setActiveTable("history")
    );
}


function setupTransferPanel() {
    const methodButtons = document.querySelectorAll(
        ".transfer-method"
    );

    const destinationInput = document.getElementById(
        "transfer-destination"
    );

    const transferStatus = document.getElementById(
        "transfer-status"
    );

    const transferSubmit = document.getElementById(
        "transfer-submit"
    );

    const transferWindowSelect = document.getElementById(
        "transfer-window"
    );

    const transferHoursGroup = document.getElementById(
        "transfer-hours-group"
    );

    const transferHoursInput = document.getElementById(
        "transfer-hours"
    );

    const usernameLabel = document.querySelector(
        'label[for="transfer-username"]'
    );

    const passwordLabel = document.querySelector(
        'label[for="transfer-password"]'
    );

    const usernameInput = document.getElementById(
        "transfer-username"
    );

    const passwordInput = document.getElementById(
        "transfer-password"
    );

    const destinationPlaceholders = {
        ftp: "ftp://sunucu/dizin",
        sftp: "sftp://sunucu/dizin",
        "json-api": "https://sunucu/api/readings"
    };

    const credentialSettings = {
        ftp: {
            usernameLabel: "FTP kullanıcı adı",
            usernamePlaceholder: "FTP kullanıcı adı",
            passwordLabel: "FTP parolası",
            passwordPlaceholder: "FTP parolası"
        },
        sftp: {
            usernameLabel: "SFTP kullanıcı adı",
            usernamePlaceholder: "SFTP kullanıcı adı",
            passwordLabel: "SFTP parolası",
            passwordPlaceholder: "SFTP parolası"
        },
        "json-api": {
            usernameLabel: "API kullanıcı adı",
            usernamePlaceholder: "API kullanıcı adı",
            passwordLabel: "API anahtarı",
            passwordPlaceholder: "API anahtarı veya token"
        }
    };

    function updateTransferWindowFields() {
        const isCustomWindow = (
            transferWindowSelect.value === "custom"
        );

        transferHoursGroup.hidden = !isCustomWindow;
        transferHoursInput.required = isCustomWindow;
    }

    function updateTransferFields() {
        const settings = credentialSettings[
            selectedTransferMethod
        ];

        usernameLabel.textContent =
            settings.usernameLabel;
        usernameInput.placeholder =
            settings.usernamePlaceholder;
        passwordLabel.textContent =
            settings.passwordLabel;
        passwordInput.placeholder =
            settings.passwordPlaceholder;
    }

    updateTransferFields();
    updateTransferWindowFields();

    transferWindowSelect.addEventListener(
        "change",
        updateTransferWindowFields
    );

    transferSubmit.addEventListener(
        "click",
        sendTransferRequest
    );

    for (const button of methodButtons) {
        button.addEventListener(
            "click",
            () => {
                selectedTransferMethod =
                    button.dataset.method;

                for (const methodButton of methodButtons) {
                    methodButton.classList.toggle(
                        "is-selected",
                        methodButton === button
                    );
                }

                destinationInput.placeholder =
                    destinationPlaceholders[
                        selectedTransferMethod
                    ];

                updateTransferFields();

                transferStatus.textContent =
                    `${selectedTransferMethod.toUpperCase()} yöntemi seçildi.`;

                transferStatus.className =
                    "transfer-status";
            }
        );
    }
}


async function sendTransferRequest() {
    const transferStatus = document.getElementById(
        "transfer-status"
    );

    const transferSubmit = document.getElementById(
        "transfer-submit"
    );

    const destination = document.getElementById(
        "transfer-destination"
    ).value.trim();

    const username = document.getElementById(
        "transfer-username"
    ).value.trim();

    const password = document.getElementById(
        "transfer-password"
    ).value;

    const fileFormat = document.getElementById(
        "transfer-format"
    ).value;

    const transferWindow = document.getElementById(
        "transfer-window"
    ).value;

    const transferHours = Number(
        document.getElementById(
            "transfer-hours"
        ).value
    );

    const {
        deviceKey,
        measurementKey,
        startDate,
        endDate
    } = getFilterValues();

    if (!destination) {
        transferStatus.textContent =
            "Hedef adres girilmelidir.";
        transferStatus.className =
            "transfer-status is-error";
        return;
    }

    if (
        transferWindow === "custom"
        && (
            !Number.isInteger(transferHours)
            || transferHours < 1
            || transferHours > 24
        )
    ) {
        transferStatus.textContent =
            "Saat aralığı 1 ile 24 arasında tam sayı olmalıdır.";
        transferStatus.className =
            "transfer-status is-error";
        return;
    }

    const requestBody = {
        method: selectedTransferMethod,
        format: fileFormat,
        window: transferWindow,
        hours: transferWindow === "custom"
            ? transferHours
            : null,
        destination,
        username,
        password,
        filters: {
            device_key: deviceKey,
            measurement_key: measurementKey,
            start_date: startDate,
            end_date: endDate
        }
    };

    transferSubmit.disabled = true;
    transferSubmit.textContent =
        "Kontrol ediliyor...";
    transferStatus.textContent =
        "Aktarım isteği doğrulanıyor...";
    transferStatus.className =
        "transfer-status";

    try {
        const response = await fetch(
            "/api/transfers",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(
                    requestBody
                )
            }
        );

        const result = await response.json();

        if (!response.ok) {
            let errorMessage = Array.isArray(
                result.errors
            )
                ? result.errors.join(" ")
                : "Aktarım isteği reddedildi.";

            if (result.local_file) {
                errorMessage +=
                    ` Yerel kopya: ${result.local_file.directory}\\`
                    + `${result.local_file.file_name}.`;
            }

            throw new Error(
                errorMessage
            );
        }

        const fileSizeKb = (
            Number(result.content_size || 0) / 1024
        ).toFixed(1);

        const transferMethodNames = {
            ftp: "FTP",
            sftp: "SFTP",
            "json-api": "JSON API"
        };

        const transferMethod =
            transferMethodNames[result.method]
            || result.method.toUpperCase();

        let localFileMessage = "";

        if (result.local_file) {
            if (result.local_file.deleted_after_transfer) {
                localFileMessage =
                    " Geçici aktarım dosyası gönderimden sonra silindi.";
            } else if (result.local_file.cleanup_error) {
                localFileMessage =
                    " Aktarım başarılı ancak geçici dosya silinemedi: "
                    + `${result.local_file.cleanup_error}`;
            } else {
                localFileMessage =
                    ` Yerel kopya: ${result.local_file.directory}\\`
                    + `${result.local_file.file_name}.`;
            }
        }

        if (result.transfer) {
            transferStatus.textContent =
                `${result.file_name} ${transferMethod} sunucusuna ` +
                `başarıyla gönderildi.${localFileMessage}`;
        } else {
            transferStatus.textContent =
                `${result.record_count} kayıt hazır. ` +
                `Dosya: ${result.file_name} ` +
                `(${fileSizeKb} KB).${localFileMessage}`;
        }
        transferStatus.className =
            "transfer-status is-success";
    } catch (error) {
        transferStatus.textContent =
            `Aktarım hazırlanamadı: ${error.message}`;
        transferStatus.className =
            "transfer-status is-error";
    } finally {
        transferSubmit.disabled = false;
        transferSubmit.textContent =
            "Seçili listeyi gönder";

        loadTransferHistory();
    }
}


function getTransferMethodLabel(method) {
    return {
        ftp: "FTP",
        sftp: "SFTP",
        "json-api": "JSON API"
    }[method] || String(method || "-").toUpperCase();
}


function getTransferWindowLabel(record) {
    if (
        record.transfer_window === "custom"
        && record.window_hours
    ) {
        return `Son ${record.window_hours} saat`;
    }

    return "Mevcut filtreler";
}


function getTransferStatusLabel(status) {
    return {
        PREPARED: "Hazırlanıyor",
        SUCCESS: "Başarılı",
        FAILED: "Başarısız"
    }[status] || status || "Bilinmiyor";
}


function prepareTransferRetry(record) {
    const methodButton = document.querySelector(
        `.transfer-method[data-method="${record.method}"]`
    );

    if (methodButton) {
        methodButton.click();
    }

    document.getElementById(
        "transfer-format"
    ).value = record.file_format || "csv";

    const transferWindow = document.getElementById(
        "transfer-window"
    );

    transferWindow.value = record.transfer_window === "custom"
        ? "custom"
        : "manual";

    document.getElementById(
        "transfer-hours"
    ).value = record.window_hours || 3;

    transferWindow.dispatchEvent(
        new Event("change")
    );

    document.getElementById(
        "transfer-destination"
    ).value = record.destination || "";

    const savedFilters = record.filters || {};
    const filterFields = {
        "device-filter": savedFilters.device_key || "",
        "measurement-filter": savedFilters.measurement_key || "",
        "start-date": savedFilters.start_date || "",
        "end-date": savedFilters.end_date || ""
    };

    for (const [fieldId, value] of Object.entries(
        filterFields
    )) {
        const field = document.getElementById(fieldId);

        if (field) {
            field.value = value;
            field.dispatchEvent(
                new Event("change")
            );
        }
    }

    document.getElementById(
        "transfer-username"
    ).value = "";

    document.getElementById(
        "transfer-password"
    ).value = "";

    const transferStatus = document.getElementById(
        "transfer-status"
    );

    transferStatus.textContent =
        "Aktarım bilgileri ve filtreler forma getirildi. "
        + "Kullanıcı adı ve parolayı girip gönderin.";
    transferStatus.className =
        "transfer-status";

    document.querySelector(
        ".transfer-panel"
    ).scrollIntoView({
        behavior: "smooth",
        block: "start"
    });

    document.getElementById(
        "transfer-destination"
    ).focus();
}


function renderTransferHistory(records) {
    const list = document.getElementById(
        "transfer-history-list"
    );

    const count = document.getElementById(
        "transfer-history-count"
    );

    list.innerHTML = "";
    count.textContent = `${records.length} kayıt`;

    if (!records.length) {
        const emptyMessage = document.createElement("p");
        emptyMessage.className = "transfer-history-empty";
        emptyMessage.textContent =
            "Henüz aktarım geçmişi bulunmuyor.";
        list.appendChild(emptyMessage);
        return;
    }

    for (const record of records) {
        const item = document.createElement("article");
        item.className = "transfer-history-item";

        const heading = document.createElement("div");
        heading.className = "transfer-history-item-heading";

        const method = document.createElement("strong");
        method.textContent = getTransferMethodLabel(
            record.method
        );

        const status = document.createElement("span");
        status.className =
            `transfer-history-badge status-${String(
                record.status || "unknown"
            ).toLowerCase()}`;
        status.textContent = getTransferStatusLabel(
            record.status
        );

        heading.append(
            method,
            status
        );

        const metadata = document.createElement("p");
        metadata.className = "transfer-history-item-meta";
        metadata.textContent = [
            getTransferWindowLabel(record),
            `${record.record_count || 0} kayıt`,
            `${(
                Number(record.content_size || 0) / 1024
            ).toFixed(1)} KB`,
            formatTimestamp(record.created_at)
        ].join(" · ");

        item.append(
            heading,
            metadata
        );

        if (record.error) {
            const error = document.createElement("p");
            error.className = "transfer-history-item-error";
            error.textContent = record.error;
            item.appendChild(error);
        }

        if (record.status === "FAILED") {
            const retryButton = document.createElement("button");
            retryButton.type = "button";
            retryButton.className = "transfer-history-retry";
            retryButton.textContent = "Tekrar hazırla";
            retryButton.addEventListener(
                "click",
                () => prepareTransferRetry(record)
            );
            item.appendChild(retryButton);
        }

        list.appendChild(item);
    }
}


async function loadTransferHistory() {
    const status = document.getElementById(
        "transfer-history-status"
    );

    try {
        const response = await fetch(
            "/api/transfers/history?limit=10"
        );

        if (!response.ok) {
            throw new Error(
                "Aktarım geçmişi API isteği başarısız."
            );
        }

        const records = await response.json();
        renderTransferHistory(records);
        status.textContent = "Son 10 kayıt";
    } catch (error) {
        status.textContent =
            "Aktarım geçmişi yüklenemedi.";
        console.error(
            "Aktarım geçmişi yüklenemedi:",
            error
        );
    }
}


function setupTransferHistory() {
    const panel = document.getElementById(
        "transfer-history-panel"
    );

    const refreshButton = document.getElementById(
        "refresh-transfer-history"
    );

    refreshButton.addEventListener(
        "click",
        loadTransferHistory
    );

    panel.addEventListener(
        "toggle",
        () => {
            if (panel.open) {
                loadTransferHistory();
            }
        }
    );

    loadTransferHistory();
}


function setupFilters() {
    const filterIds = [
        "device-filter",
        "measurement-filter",
        "start-date",
        "end-date",
        "transfer-format"
    ];

    for (const filterId of filterIds) {
        const filter = document.getElementById(filterId);

        filter.addEventListener(
            "change",
            () => {
                renderTable();
                updateDownloadLink();

                if (activeTable === "history") {
                    loadHistory().catch((error) => {
                        console.error(
                            "Geçmiş kayıtlar yüklenemedi:",
                            error
                        );
                    });
                }
            }
        );
    }

    const clearButton = document.getElementById(
        "clear-filters"
    );

    clearButton.addEventListener(
        "click",
        () => {
            document.getElementById(
                "device-filter"
            ).value = "";

            document.getElementById(
                "measurement-filter"
            ).value = "";

            document.getElementById(
                "start-date"
            ).value = "";

            document.getElementById(
                "end-date"
            ).value = "";

            renderTable();
            updateDownloadLink();

            if (activeTable === "history") {
                loadHistory().catch((error) => {
                    console.error(
                        "Geçmiş kayıtlar yüklenemedi:",
                        error
                    );
                });
            }
        }
    );
}


setupStatusDetails();
setupTableTabs();
setupFilters();
setupTransferPanel();
setupTransferHistory();
refreshReadings();

setInterval(
    refreshReadings,
    5000
);


function setupDeviceModal() {
    const modal = document.getElementById(
        "device-modal"
    );

    const openButton = document.getElementById(
        "open-device-modal"
    );

    const closeButton = document.getElementById(
        "close-device-modal"
    );

    const cancelButton = document.getElementById(
        "cancel-device-modal"
    );

    const refreshDevicesButton = document.getElementById(
        "refresh-device-list"
    );

    const viewButtons = [
        ...document.querySelectorAll(
            "[data-device-view]"
        )
    ];

    const deviceSearchInput = document.getElementById(
        "managed-device-search"
    );

    const deviceStatusFilter = document.getElementById(
        "managed-device-status-filter"
    );

    if (
        !modal
        || !openButton
        || !closeButton
        || !cancelButton
    ) {
        return;
    }

    function openModal() {
        resetDeviceForm();
        setDeviceManagementView("list");
        modal.classList.add("is-open");
        modal.setAttribute(
            "aria-hidden",
            "false"
        );
        document.body.classList.add(
            "modal-open"
        );

        loadManagedDevices();
    }

    function closeModal() {
        resetDeviceForm();
        modal.classList.remove("is-open");
        modal.setAttribute(
            "aria-hidden",
            "true"
        );
        document.body.classList.remove(
            "modal-open"
        );
    }

    openButton.addEventListener(
        "click",
        openModal
    );

    if (refreshDevicesButton) {
        refreshDevicesButton.addEventListener(
            "click",
            loadManagedDevices
        );
    }

    viewButtons.forEach(
        (button) => {
            button.addEventListener(
                "click",
                () => {
                    if (!confirmDiscardDeviceChanges()) {
                        return;
                    }

                    const view = button.dataset.deviceView;

                    resetDeviceForm();
                    setDeviceManagementView(view);

                    if (view === "list") {
                        loadManagedDevices();
                    }
                }
            );
        }
    );

    if (deviceSearchInput) {
        deviceSearchInput.addEventListener(
            "input",
            () => {
                selectedManagedDeviceKeys.clear();
                renderManagedDeviceList();
            }
        );
    }

    if (deviceStatusFilter) {
        deviceStatusFilter.addEventListener(
            "change",
            () => {
                selectedManagedDeviceKeys.clear();
                renderManagedDeviceList();
            }
        );
    }

    closeButton.addEventListener(
        "click",
        () => {
            if (confirmDiscardDeviceChanges()) {
                closeModal();
            }
        }
    );

    cancelButton.addEventListener(
        "click",
        () => {
            if (confirmDiscardDeviceChanges()) {
                closeModal();
            }
        }
    );

    modal.addEventListener(
        "click",
        (event) => {
            if (
                event.target === modal
                && confirmDiscardDeviceChanges()
            ) {
                closeModal();
            }
        }
    );

    document.addEventListener(
        "keydown",
        (event) => {
            if (
                event.key === "Escape"
                && modal.classList.contains("is-open")
                && confirmDiscardDeviceChanges()
            ) {
                closeModal();
            }
        }
    );

    loadManagedDevices();
}


function updateDeviceFilterOptions(devices) {
    const filter = document.getElementById(
        "device-filter"
    );

    if (!filter) {
        return;
    }

    const selectedKey = filter.value;
    filter.replaceChildren();

    const allDevicesOption = document.createElement(
        "option"
    );
    allDevicesOption.value = "";
    allDevicesOption.textContent = "Tüm cihazlar";
    filter.appendChild(allDevicesOption);

    for (const device of devices) {
        const option = document.createElement(
            "option"
        );
        option.value = device.key || "";
        option.textContent = device.name || device.key || "Bilinmeyen cihaz";
        filter.appendChild(option);
    }

    const selectedDeviceStillExists = devices.some(
        (device) => device.key === selectedKey
    );

    filter.value = selectedDeviceStillExists
        ? selectedKey
        : "";
}


function updateMeasurementFilterOptions(devices) {
    const filter = document.getElementById(
        "measurement-filter"
    );

    if (!filter) {
        return;
    }

    const selectedKey = filter.value;
    const measurementsByKey = new Map();

    for (const device of devices) {
        for (const measurement of device.measurements || []) {
            if (!measurementsByKey.has(measurement.key)) {
                measurementsByKey.set(
                    measurement.key,
                    measurement.name || measurement.key
                );
            }
        }
    }

    filter.replaceChildren();

    const allMeasurementsOption = document.createElement(
        "option"
    );
    allMeasurementsOption.value = "";
    allMeasurementsOption.textContent = "Tüm ölçümler";
    filter.appendChild(allMeasurementsOption);

    for (const [key, name] of measurementsByKey) {
        const option = document.createElement(
            "option"
        );
        option.value = key || "";
        option.textContent = name;
        filter.appendChild(option);
    }

    filter.value = measurementsByKey.has(selectedKey)
        ? selectedKey
        : "";
}


function updateBulkTemplateOptions(devices) {
    const select = document.getElementById(
        "bulk-template-device"
    );

    if (!select) {
        return;
    }

    const selectedKey = select.value;
    select.replaceChildren();

    const emptyOption = document.createElement(
        "option"
    );
    emptyOption.value = "";
    emptyOption.textContent = "Cihaz seçin";
    select.appendChild(emptyOption);

    for (const device of devices) {
        const option = document.createElement(
            "option"
        );
        option.value = device.key || "";
        option.textContent = device.name || device.key || "Bilinmeyen cihaz";
        select.appendChild(option);
    }

    select.value = devices.some(
        (device) => device.key === selectedKey
    )
        ? selectedKey
        : "";
}


function setDeviceManagementView(view) {
    const sections = {
        list: document.getElementById("device-view-list"),
        single: document.getElementById("device-view-single"),
        advanced: document.getElementById("device-view-advanced")
    };
    const bulkContent = document.getElementById(
        "device-bulk-content"
    );
    const bulkFormContent = document.getElementById(
        "device-bulk-form-content"
    );
    const csvContent = document.getElementById(
        "device-csv-content"
    );

    if (
        !sections.list
        || !sections.single
        || !sections.advanced
        || !bulkContent
        || !bulkFormContent
        || !csvContent
    ) {
        return;
    }

    sections.list.hidden = view !== "list";
    sections.single.hidden = view !== "single";
    sections.advanced.hidden = !["bulk", "csv"].includes(view);
    bulkContent.hidden = view !== "bulk";
    bulkFormContent.hidden = view !== "bulk";
    csvContent.hidden = view !== "csv";

    document.querySelectorAll(
        "[data-device-view]"
    ).forEach(
        (button) => button.classList.toggle(
            "is-active",
            button.dataset.deviceView === view
        )
    );

    const title = document.getElementById(
        "device-modal-title"
    );

    if (!title) {
        return;
    }

    const titles = {
        list: "Kayıtlı cihazlar",
        single: "Yeni cihaz ekle",
        bulk: "Şablondan çoğalt",
        csv: "CSV ile içe aktar"
    };

    title.textContent = titles[view] || titles.list;
}


function updateManagedDeviceSelectionUi() {
    const bulkActions = document.getElementById(
        "managed-device-bulk-actions"
    );
    const countLabel = document.getElementById(
        "managed-device-selection-count"
    );
    const selectAll = document.getElementById(
        "select-all-managed-devices"
    );
    const visibleCheckboxes = [
        ...document.querySelectorAll(
            "[data-managed-device-select]"
        )
    ];
    const selectedCount = selectedManagedDeviceKeys.size;
    const visibleSelectedCount = visibleCheckboxes.filter(
        (checkbox) => checkbox.checked
    ).length;

    if (bulkActions) {
        bulkActions.hidden = selectedCount === 0;
    }

    if (countLabel) {
        countLabel.textContent = `${selectedCount} cihaz seçildi`;
    }

    if (selectedCount === 0) {
        const feedback = document.getElementById(
            "managed-device-bulk-feedback"
        );

        if (feedback) {
            feedback.textContent = "";
            feedback.className = "managed-device-bulk-feedback";
        }
    }

    if (selectAll) {
        selectAll.checked = visibleCheckboxes.length > 0
            && visibleSelectedCount === visibleCheckboxes.length;
        selectAll.indeterminate = visibleSelectedCount > 0
            && visibleSelectedCount < visibleCheckboxes.length;
    }
}


function toggleManagedDeviceSelection(deviceKey, isSelected) {
    if (isSelected) {
        selectedManagedDeviceKeys.add(deviceKey);
    } else {
        selectedManagedDeviceKeys.delete(deviceKey);
    }

    updateManagedDeviceSelectionUi();
}


async function runManagedDeviceBulkAction(action) {
    const selectedKeys = [
        ...selectedManagedDeviceKeys
    ];

    if (!selectedKeys.length) {
        return;
    }

    if (action === "delete") {
        const confirmed = window.confirm(
            `${selectedKeys.length} cihaz ve ölçüm tanımları silinecek. Devam etmek istiyor musunuz?`
        );

        if (!confirmed) {
            return;
        }
    }

    const feedback = document.getElementById(
        "managed-device-bulk-feedback"
    );
    const buttons = [
        ...document.querySelectorAll(
            "[data-managed-bulk-action]"
        )
    ];

    buttons.forEach(
        (button) => {
            button.disabled = true;
        }
    );

    if (feedback) {
        feedback.textContent = "Toplu işlem uygulanıyor...";
        feedback.className = "managed-device-bulk-feedback";
    }

    try {
        const response = await fetch(
            "/api/devices/bulk-action",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    device_keys: selectedKeys,
                    action
                })
            }
        );
        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.error || "Toplu cihaz işlemi başarısız."
            );
        }

        selectedManagedDeviceKeys.clear();

        if (feedback) {
            feedback.textContent = result.message;
            feedback.className =
                "managed-device-bulk-feedback is-success";
        }

        await loadManagedDevices();
        await refreshReadings();
    } catch (error) {
        if (feedback) {
            feedback.textContent = `Toplu işlem başarısız: ${error.message}`;
            feedback.className =
                "managed-device-bulk-feedback is-error";
        }
    } finally {
        buttons.forEach(
            (button) => {
                button.disabled = false;
            }
        );
        updateManagedDeviceSelectionUi();
    }
}


function setupManagedDeviceBulkActions() {
    const selectAll = document.getElementById(
        "select-all-managed-devices"
    );

    if (selectAll) {
        selectAll.addEventListener(
            "change",
            () => {
                const shouldSelect = selectAll.checked;

                document.querySelectorAll(
                    "[data-managed-device-select]"
                ).forEach(
                    (checkbox) => {
                        checkbox.checked = shouldSelect;
                        toggleManagedDeviceSelection(
                            checkbox.dataset.managedDeviceSelect,
                            shouldSelect
                        );
                    }
                );
                renderManagedDeviceList();
            }
        );
    }

    document.querySelectorAll(
        "[data-managed-bulk-action]"
    ).forEach(
        (button) => button.addEventListener(
            "click",
            () => runManagedDeviceBulkAction(
                button.dataset.managedBulkAction
            )
        )
    );
}


function createManagedDeviceCard(device) {
    const card = document.createElement("article");
    card.className = "managed-device-card";

    const details = document.createElement("div");
    details.className = "managed-device-details";

    const name = document.createElement("strong");
    name.className = "managed-device-name";
    name.textContent = device.name || "Bilinmeyen cihaz";

    const key = document.createElement("span");
    key.className = "managed-device-key";
    key.textContent = device.key || "-";

    const meta = document.createElement("span");
    meta.className = "managed-device-meta";
    meta.textContent = `${String(device.protocol || "tcp").toUpperCase()} · Unit ID ${device.unit_id ?? "-"}`;

    const measurements = Array.isArray(device.measurements)
        ? device.measurements
        : [];
    const measurementNames = measurements
        .map(
            (measurement) => measurement.name || measurement.key
        )
        .filter(Boolean);

    const measurementSummary = document.createElement("span");
    measurementSummary.className = "managed-device-measurements";

    if (!measurementNames.length) {
        measurementSummary.textContent = "Ölçüm tanımı yok";
    } else {
        const visibleNames = measurementNames.slice(0, 3);
        const remainingCount = measurementNames.length - visibleNames.length;
        measurementSummary.textContent = `Ölçümler: ${visibleNames.join(
            ", "
        )}${remainingCount > 0 ? ` +${remainingCount}` : ""}`;
    }

    const extraDetails = document.createElement("details");
    extraDetails.className = "managed-device-extra";

    const extraSummary = document.createElement("summary");
    extraSummary.textContent = "Bağlantı ve ölçüm ayrıntıları";

    const extraContent = document.createElement("div");
    extraContent.className = "managed-device-extra-content";

    const connection = document.createElement("p");
    connection.className = "managed-device-connection";
    const protocol = String(device.protocol || "tcp").toLowerCase();

    if (protocol === "tcp") {
        connection.textContent = `Bağlantı: TCP · ${device.host || "-"}:${device.port ?? "-"}`;
    } else if (device.transport === "serial") {
        connection.textContent = [
            "Bağlantı: RTU",
            device.serial_port || "-",
            `${device.baudrate ?? "-"} baud`,
            `Parity ${device.parity || "-"}`,
            `${device.bytesize ?? "-"} bit / ${device.stopbits ?? "-"} stopbit`
        ].join(" · ");
    } else {
        connection.textContent = "Bağlantı: RTU · Kod içi simülasyon";
    }

    const measurementList = document.createElement("ul");
    measurementList.className = "managed-device-measurement-list";

    if (!measurements.length) {
        const emptyMeasurement = document.createElement("li");
        emptyMeasurement.textContent = "Tanımlı ölçüm bulunmuyor.";
        measurementList.appendChild(emptyMeasurement);
    } else {
        for (const measurement of measurements) {
            const measurementItem = document.createElement("li");
            const measurementName = measurement.name || measurement.key || "Ölçüm";
            const measurementUnit = measurement.unit
                ? ` · ${measurement.unit}`
                : "";
            measurementItem.textContent = [
                measurementName,
                `Register ${measurement.address ?? "-"}`,
                `Adet ${measurement.count ?? "-"}`,
                String(measurement.data_type || "-").toUpperCase(),
                `Ölçek ${measurement.scale ?? "-"}${measurementUnit}`
            ].join(" · ");
            measurementList.appendChild(measurementItem);
        }
    }

    extraContent.append(
        connection,
        measurementList
    );
    extraDetails.append(
        extraSummary,
        extraContent
    );

    details.append(
        name,
        key,
        meta,
        measurementSummary,
        extraDetails
    );

    const actions = document.createElement("div");
    actions.className = "managed-device-actions";

    const selectionLabel = document.createElement("label");
    selectionLabel.className = "managed-device-selection";

    const selectionInput = document.createElement("input");
    selectionInput.type = "checkbox";
    selectionInput.dataset.managedDeviceSelect = device.key || "";
    selectionInput.checked = selectedManagedDeviceKeys.has(
        device.key
    );
    selectionInput.setAttribute(
        "aria-label",
        `${device.name || device.key || "Cihaz"} seç`
    );
    selectionInput.addEventListener(
        "change",
        () => toggleManagedDeviceSelection(
            device.key,
            selectionInput.checked
        )
    );

    const selectionText = document.createElement("span");
    selectionText.textContent = "Seç";
    selectionLabel.append(
        selectionInput,
        selectionText
    );

    const status = document.createElement("span");
    const isEnabled = device.enabled !== false;
    status.className = isEnabled
        ? "managed-device-status is-enabled"
        : "managed-device-status is-disabled";
    status.textContent = isEnabled
        ? "ETKİN"
        : "DEVRE DIŞI";

    if (!measurements.length) {
        const addMeasurementButton = document.createElement("button");
        addMeasurementButton.type = "button";
        addMeasurementButton.className = "managed-device-action is-primary";
        addMeasurementButton.textContent = "+ Ölçüm ekle";
        addMeasurementButton.title = "Bu cihaza ilk ölçüm tanımını ekle";
        addMeasurementButton.addEventListener(
            "click",
            () => {
                startDeviceEdit(device);
                document.getElementById("add-measurement")?.click();
                document.getElementById(
                    "device-modal-title"
                ).textContent = "Cihaza ölçüm ekle";
                document.getElementById(
                    "device-modal-description"
                ).textContent =
                    "Cihaz bağlantısını değiştirmeden yeni ölçüm tanımı ekleyin.";
                setDeviceFormFeedback(
                    "Yeni ölçüm tanımını doldurup kaydedin."
                );
            }
        );
        actions.appendChild(addMeasurementButton);
    }

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "managed-device-action";
    editButton.textContent = "Düzenle";
    editButton.addEventListener(
        "click",
        () => startDeviceEdit(device)
    );

    const cloneButton = document.createElement("button");
    cloneButton.type = "button";
    cloneButton.className = "managed-device-action";
    cloneButton.textContent = "Şablon olarak kullan";
    cloneButton.title = "Bu cihazı yeni cihaz için şablon olarak kullan";
    cloneButton.addEventListener(
        "click",
        () => startDeviceClone(device)
    );

    const toggleButton = document.createElement("button");
    toggleButton.type = "button";
    toggleButton.className = "managed-device-action";
    toggleButton.textContent = isEnabled
        ? "Devre dışı bırak"
        : "Etkinleştir";
    toggleButton.addEventListener(
        "click",
        () => updateManagedDeviceStatus(
            device,
            !isEnabled
        )
    );

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "managed-device-action is-danger";
    deleteButton.textContent = "Sil";
    deleteButton.addEventListener(
        "click",
        () => deleteManagedDevice(device)
    );

    actions.append(
        selectionLabel,
        status,
        editButton,
        cloneButton,
        toggleButton,
        deleteButton
    );

    card.append(
        details,
        actions
    );

    return card;
}


function renderManagedDeviceList() {
    const list = document.getElementById(
        "managed-device-list"
    );

    if (!list) {
        return;
    }

    const availableKeys = new Set(
        managedDevices.map(
            (device) => device.key
        )
    );
    selectedManagedDeviceKeys.forEach(
        (deviceKey) => {
            if (!availableKeys.has(deviceKey)) {
                selectedManagedDeviceKeys.delete(deviceKey);
            }
        }
    );

    const searchInput = document.getElementById(
        "managed-device-search"
    );
    const statusFilter = document.getElementById(
        "managed-device-status-filter"
    );
    const searchText = (searchInput?.value || "")
        .trim()
        .toLocaleLowerCase("tr-TR");
    const selectedStatus = statusFilter?.value || "all";

    const filteredDevices = managedDevices.filter(
        (device) => {
            const searchableText = [
                device.name,
                device.key,
                device.protocol,
                device.unit_id
            ]
                .filter((value) => value !== null && value !== undefined)
                .join(" ")
                .toLocaleLowerCase("tr-TR");
            const searchTokens = searchableText.split(
                /[\s_.:/-]+/
            );
            const isEnabled = device.enabled !== false;
            const matchesSearch = !searchText
                || (
                    searchText.length === 1
                        ? searchTokens.includes(searchText)
                        : searchableText.includes(searchText)
                );
            const matchesStatus = selectedStatus === "all"
                || (selectedStatus === "enabled" && isEnabled)
                || (selectedStatus === "disabled" && !isEnabled);

            return matchesSearch && matchesStatus;
        }
    );

    list.replaceChildren();

    if (!managedDevices.length) {
        const emptyMessage = document.createElement("p");
        emptyMessage.className = "device-list-message";
        emptyMessage.textContent = "Kayıtlı cihaz bulunamadı.";
        list.appendChild(emptyMessage);
        updateManagedDeviceSelectionUi();
        return;
    }

    if (!filteredDevices.length) {
        const emptyMessage = document.createElement("p");
        emptyMessage.className = "device-list-message";
        emptyMessage.textContent =
            "Arama ve durum filtresine uygun cihaz bulunamadı.";
        list.appendChild(emptyMessage);
        updateManagedDeviceSelectionUi();
        return;
    }

    for (const device of filteredDevices) {
        list.appendChild(
            createManagedDeviceCard(device)
        );
    }

    updateManagedDeviceSelectionUi();
}


async function loadManagedDevices() {
    const list = document.getElementById(
        "managed-device-list"
    );

    if (!list) {
        return;
    }

    list.replaceChildren();

    const loadingMessage = document.createElement("p");
    loadingMessage.className = "device-list-message";
    loadingMessage.textContent = "Cihazlar yükleniyor...";
    list.appendChild(loadingMessage);

    try {
        const response = await fetch("/api/devices");
        const devices = await response.json();

        if (!response.ok) {
            throw new Error(
                devices.error || "Cihaz listesi alınamadı."
            );
        }

        selectedManagedDeviceKeys.clear();
        managedDevices = devices;
        updateBulkTemplateOptions(devices);
        updateDeviceFilterOptions(devices);
        updateMeasurementFilterOptions(devices);
        renderManagedDeviceList();
    } catch (error) {
        list.replaceChildren();

        const errorMessage = document.createElement("p");
        errorMessage.className = "device-list-message is-error";
        errorMessage.textContent =
            `Cihaz listesi yüklenemedi: ${error.message}`;
        list.appendChild(errorMessage);
    }
}


function getBulkNumber(id) {
    const field = document.getElementById(id);
    const rawValue = field.value.trim();

    if (rawValue === "") {
        return null;
    }

    const value = Number(rawValue);

    return Number.isInteger(value)
        ? value
        : null;
}


function findAvailableStartUnitId(count) {
    const usedUnitIds = new Set(
        managedDevices.map(
            (device) => device.unit_id
        )
    );

    for (
        let startUnitId = 1;
        startUnitId + count - 1 <= 247;
        startUnitId++
    ) {
        const blockIsAvailable = Array.from(
            { length: count },
            (_, index) => startUnitId + index
        ).every(
            (unitId) => !usedUnitIds.has(unitId)
        );

        if (blockIsAvailable) {
            return startUnitId;
        }
    }

    return null;
}


function updateBulkUnitIdMode() {
    const selectedMode = document.querySelector(
        'input[name="bulk-unit-id-mode"]:checked'
    );
    const manualGroup = document.getElementById(
        "bulk-manual-unit-id-group"
    );

    if (!selectedMode || !manualGroup) {
        return;
    }

    manualGroup.hidden = selectedMode.value !== "manual";
}


function buildBulkDevices(template, values) {
    return Array.from(
        { length: values.count },
        (_, index) => {
            const number = values.startNumber + index;
            const device = {
                key: `${values.keyPrefix}${number}`,
                name: `${values.namePrefix} ${number}`,
                protocol: template.protocol,
                enabled: true,
                unit_id: values.startUnitId + index,
                timeout: template.timeout ?? 3,
                retry_count: template.retry_count ?? 2,
                retry_delay: template.retry_delay ?? 0.5,
                measurements: (template.measurements || []).map(
                    (measurement) => ({ ...measurement })
                )
            };

            if (template.protocol === "tcp") {
                device.host = template.host;
                device.port = template.port;
            } else {
                device.transport = template.transport || "memory";

                if (device.transport === "serial") {
                    device.serial_port = template.serial_port;
                    device.baudrate = template.baudrate;
                    device.parity = template.parity;
                    device.stopbits = template.stopbits;
                    device.bytesize = template.bytesize;
                }
            }

            return device;
        }
    );
}


function setupBulkDeviceForm() {
    const form = document.getElementById(
        "bulk-device-form"
    );

    const feedback = document.getElementById(
        "bulk-device-feedback"
    );

    const submitButton = document.getElementById(
        "bulk-create-devices"
    );

    if (!form || !feedback || !submitButton) {
        return;
    }

    document.querySelectorAll(
        'input[name="bulk-unit-id-mode"]'
    ).forEach(
        (radio) => radio.addEventListener(
            "change",
            updateBulkUnitIdMode
        )
    );

    updateBulkUnitIdMode();

    form.addEventListener(
        "submit",
        async (event) => {
            event.preventDefault();

            const templateKey = document.getElementById(
                "bulk-template-device"
            ).value;
            const template = managedDevices.find(
                (device) => device.key === templateKey
            );
            const keyPrefix = document.getElementById(
                "bulk-key-prefix"
            ).value.trim();
            const namePrefix = document.getElementById(
                "bulk-name-prefix"
            ).value.trim();
            const startNumber = getBulkNumber(
                "bulk-start-number"
            );
            const count = getBulkNumber(
                "bulk-device-count"
            );
            const selectedUnitIdMode = document.querySelector(
                'input[name="bulk-unit-id-mode"]:checked'
            )?.value || "auto";
            const manualStartUnitId = getBulkNumber(
                "bulk-start-unit-id"
            );
            const hasValidCount = count !== null
                && count >= 1
                && count <= 1000;
            const startUnitId = selectedUnitIdMode === "auto"
                && hasValidCount
                ? findAvailableStartUnitId(count)
                : manualStartUnitId;

            if (!template) {
                feedback.textContent = "Önce bir şablon cihaz seçin.";
                feedback.className = "device-form-feedback is-error";
                return;
            }

            if (!keyPrefix || !namePrefix) {
                feedback.textContent =
                    "Cihaz anahtarı ve cihaz adı ön ekleri boş olamaz.";
                feedback.className = "device-form-feedback is-error";
                return;
            }

            if (
                startNumber === null
                || startNumber < 1
                || !hasValidCount
                || (
                    selectedUnitIdMode === "manual"
                    && manualStartUnitId === null
                )
                || (
                    startUnitId !== null
                    && (
                        startUnitId < 1
                        || startUnitId > 247
                        || startUnitId + count - 1 > 247
                    )
                )
            ) {
                feedback.textContent = selectedUnitIdMode === "auto"
                    ? "Başlangıç numarası ve cihaz sayısını kontrol edin."
                    : "Başlangıç numarası, cihaz sayısı ve Unit ID alanlarını kontrol edin.";
                feedback.className = "device-form-feedback is-error";
                return;
            }

            if (
                selectedUnitIdMode === "auto"
                && startUnitId === null
            ) {
                feedback.textContent =
                    "Bu kadar cihaz için yeterli boş Unit ID bulunamadı. Cihaz sayısını azaltın.";
                feedback.className = "device-form-feedback is-error";
                return;
            }

            const devices = buildBulkDevices(
                template,
                {
                    keyPrefix,
                    namePrefix,
                    startNumber,
                    count,
                    startUnitId
                }
            );

            const confirmed = window.confirm(
                `${devices.length} cihaz oluşturulacak. Devam etmek istiyor musunuz?`
            );

            if (!confirmed) {
                return;
            }

            submitButton.disabled = true;
            submitButton.textContent = "Cihazlar oluşturuluyor...";
            feedback.textContent = "Cihazlar doğrulanıyor...";
            feedback.className = "device-form-feedback";

            try {
                const response = await fetch(
                    "/api/devices/bulk",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ devices })
                    }
                );

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(
                        result.details || result.error || "Toplu kayıt başarısız."
                    );
                }

                feedback.textContent =
                    `${result.count} cihaz başarıyla oluşturuldu.`;
                feedback.className = "device-form-feedback is-success";
                form.reset();
                await loadManagedDevices();
                await refreshReadings();
            } catch (error) {
                feedback.textContent =
                    `Toplu kayıt yapılamadı: ${error.message}`;
                feedback.className = "device-form-feedback is-error";
            } finally {
                submitButton.disabled = false;
                submitButton.textContent = "Cihazları oluştur";
            }
        }
    );
}


async function updateManagedDeviceStatus(device, enabled) {
    try {
        const response = await fetch(
            `/api/devices/${encodeURIComponent(device.key)}/status`,
            {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ enabled })
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.error || "Cihaz durumu değiştirilemedi."
            );
        }

        await loadManagedDevices();
        await refreshReadings();
    } catch (error) {
        window.alert(
            `Cihaz durumu değiştirilemedi: ${error.message}`
        );
    }
}


async function deleteManagedDevice(device) {
    const confirmed = window.confirm(
        `${device.name} cihazını ve ölçüm tanımlarını silmek istediğinize emin misiniz?\n\nCSV geçmiş kayıtları silinmez.`
    );

    if (!confirmed) {
        return;
    }

    try {
        const response = await fetch(
            `/api/devices/${encodeURIComponent(device.key)}`,
            {
                method: "DELETE"
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.error || "Cihaz silinemedi."
            );
        }

        await loadManagedDevices();
        await refreshReadings();
    } catch (error) {
        window.alert(
            `Cihaz silinemedi: ${error.message}`
        );
    }
}


function setDeviceFormField(id, value) {
    const field = document.getElementById(id);

    field.value = value ?? "";
}


function fillMeasurementFormRow(row, measurement) {
    const fields = {
        key: measurement.key,
        name: measurement.name,
        function_code: measurement.function_code,
        address: measurement.address,
        count: measurement.count,
        data_type: measurement.data_type,
        scale: measurement.scale,
        unit: measurement.unit
    };

    for (const [fieldName, value] of Object.entries(fields)) {
        const field = row.querySelector(
            `[data-field="${fieldName}"]`
        );

        field.value = value ?? "";
    }
}


function startDeviceEdit(device) {
    const form = document.getElementById(
        "device-form"
    );
    const title = document.getElementById(
        "device-modal-title"
    );
    const description = document.getElementById(
        "device-modal-description"
    );
    const saveButton = document.getElementById(
        "save-device"
    );
    const addMeasurementButton = document.getElementById(
        "add-measurement"
    );
    const measurementList = document.getElementById(
        "measurement-list"
    );

    if (
        !form
        || !title
        || !description
        || !saveButton
        || !addMeasurementButton
        || !measurementList
    ) {
        return;
    }

    resetDeviceForm();
    setDeviceManagementView("single");

    editingDeviceKey = device.key;
    editingDevice = device;

    title.textContent = "Cihazı düzenle";
    description.textContent =
        "Mevcut cihaz bilgilerini güvenli şekilde güncelle.";
    saveButton.textContent = "Güncellemeyi kaydet";

    suppressDeviceFormDirty = true;

    try {
        setDeviceFormField(
            "new-device-key",
            device.key
        );
        setDeviceFormField(
            "new-device-name",
            device.name
        );
        setDeviceFormField(
            "new-device-protocol",
            device.protocol
        );
        setDeviceFormField(
            "new-device-unit-id",
            device.unit_id
        );

        document.getElementById(
            "new-device-protocol"
        ).dispatchEvent(new Event("change"));

        if (device.protocol === "tcp") {
            setDeviceFormField(
                "new-device-host",
                device.host
            );
            setDeviceFormField(
                "new-device-port",
                device.port
            );
        } else {
            setDeviceFormField(
                "new-device-transport",
                device.transport || "memory"
            );
            document.getElementById(
                "new-device-transport"
            ).dispatchEvent(new Event("change"));

            setDeviceFormField(
                "new-device-serial-port",
                device.serial_port
            );
            setDeviceFormField(
                "new-device-baudrate",
                device.baudrate
            );
            setDeviceFormField(
                "new-device-parity",
                device.parity || "N"
            );
            setDeviceFormField(
                "new-device-stopbits",
                device.stopbits
            );
            setDeviceFormField(
                "new-device-bytesize",
                device.bytesize
            );
        }

        const measurements = device.measurements || [];

        for (let index = 0; index < measurements.length; index++) {
            addMeasurementButton.click();
        }

        const rows = [
            ...measurementList.querySelectorAll(
                "[data-measurement-row]"
            )
        ];

        rows.forEach((row, index) => {
            fillMeasurementFormRow(
                row,
                measurements[index] || {}
            );
        });
    } finally {
        suppressDeviceFormDirty = false;
    }

    setDeviceFormFeedback(
        "Düzenleme modu açık. Değişiklikleri kontrol edip kaydedin."
    );

    form.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}


function startDeviceClone(device) {
    startDeviceEdit(device);

    editingDeviceKey = null;
    editingDevice = null;

    setDeviceFormField(
        "new-device-key",
        `${device.key}_kopya`
    );
    setDeviceFormField(
        "new-device-name",
        `${device.name} (Kopya)`
    );
    setDeviceFormField(
        "new-device-unit-id",
        ""
    );

    document.getElementById(
        "device-modal-title"
    ).textContent = "Şablondan cihaz oluştur";
    document.getElementById(
        "device-modal-description"
    ).textContent =
        "Mevcut ayarlar dolduruldu. Benzersiz alanları kontrol edip kaydedin.";
    document.getElementById(
        "save-device"
    ).textContent = "Cihazı oluştur";
    setDeviceFormFeedback(
        "Kopya oluşturma modu açık. Anahtar ve Unit ID alanlarını kontrol edin."
    );
    deviceFormDirty = true;
}


function getDeviceFormValue(id) {
    const field = document.getElementById(id);

    return field.value.trim();
}


function getDeviceFormNumber(id) {
    const value = getDeviceFormValue(id);

    return value === ""
        ? null
        : Number(value);
}


function collectMeasurementFormData() {
    const rows = [
        ...document.querySelectorAll(
            "[data-measurement-row]"
        )
    ];

    return rows.map((row) => ({
        key: row.querySelector('[data-field="key"]').value.trim(),
        name: row.querySelector('[data-field="name"]').value.trim(),
        function_code: Number(
            row.querySelector('[data-field="function_code"]').value
        ),
        address: row.querySelector(
            '[data-field="address"]'
        ).value.trim() === ""
            ? null
            : Number(
                row.querySelector('[data-field="address"]').value
            ),
        count: row.querySelector(
            '[data-field="count"]'
        ).value.trim() === ""
            ? null
            : Number(
                row.querySelector('[data-field="count"]').value
            ),
        data_type: row.querySelector('[data-field="data_type"]').value,
        scale: row.querySelector(
            '[data-field="scale"]'
        ).value.trim() === ""
            ? null
            : Number(
                row.querySelector('[data-field="scale"]').value
            ),
        unit: row.querySelector('[data-field="unit"]').value.trim()
    }));
}


function collectDeviceFormData() {
    const protocol = getDeviceFormValue(
        "new-device-protocol"
    );

    const device = {
        key: getDeviceFormValue("new-device-key"),
        name: getDeviceFormValue("new-device-name"),
        protocol,
        enabled: editingDevice
            ? editingDevice.enabled !== false
            : true,
        unit_id: getDeviceFormNumber(
            "new-device-unit-id"
        ),
        timeout: editingDevice?.timeout ?? 3,
        retry_count: editingDevice?.retry_count ?? 2,
        retry_delay: editingDevice?.retry_delay ?? 0.5,
        measurements: collectMeasurementFormData()
    };

    if (protocol === "tcp") {
        device.host = getDeviceFormValue(
            "new-device-host"
        );
        device.port = getDeviceFormNumber(
            "new-device-port"
        );
    } else {
        device.transport = getDeviceFormValue(
            "new-device-transport"
        );

        if (device.transport === "serial") {
            device.serial_port = getDeviceFormValue(
                "new-device-serial-port"
            );
            device.baudrate = getDeviceFormNumber(
                "new-device-baudrate"
            );
            device.parity = getDeviceFormValue(
                "new-device-parity"
            );
            device.stopbits = getDeviceFormNumber(
                "new-device-stopbits"
            );
            device.bytesize = getDeviceFormNumber(
                "new-device-bytesize"
            );
        }
    }

    return device;
}


function setDeviceFormFeedback(message, type = "") {
    const feedback = document.getElementById(
        "device-form-feedback"
    );

    feedback.textContent = message;
    feedback.className = `device-form-feedback ${type}`.trim();
}


function resetMeasurementFormRows() {
    const measurementList = document.getElementById(
        "measurement-list"
    );

    const rows = [
        ...measurementList.querySelectorAll(
            "[data-measurement-row]"
        )
    ];

    rows.slice(1).forEach(
        (row) => row.remove()
    );
}


function resetDeviceForm() {
    const form = document.getElementById(
        "device-form"
    );

    suppressDeviceFormDirty = true;

    try {
        resetMeasurementFormRows();
        form.reset();
        clearDeviceFieldErrors();

        document.getElementById(
            "new-device-protocol"
        ).dispatchEvent(new Event("change"));

        document.getElementById(
            "new-device-transport"
        ).dispatchEvent(new Event("change"));
    } finally {
        suppressDeviceFormDirty = false;
    }

    editingDeviceKey = null;
    editingDevice = null;

    document.getElementById(
        "device-modal-title"
    ).textContent = "Kayıtlı cihazlar";
    document.getElementById(
        "device-modal-description"
    ).textContent = "";
    document.getElementById(
        "save-device"
    ).textContent = "Kaydet";
    setDeviceFormFeedback("");
    deviceFormDirty = false;
}


function clearDeviceFieldError(field) {
    if (!field) {
        return;
    }

    field.classList.remove("has-error");
    field.removeAttribute("aria-invalid");

    const group = field.closest(".device-form-group");
    const error = group?.querySelector(".field-error");

    if (error) {
        error.remove();
    }
}


function clearDeviceFieldErrors() {
    document.querySelectorAll(
        "#device-form input, #device-form select"
    ).forEach(
        (field) => clearDeviceFieldError(field)
    );
}


function setDeviceFieldError(field, message) {
    if (!field) {
        return;
    }

    clearDeviceFieldError(field);
    field.classList.add("has-error");
    field.setAttribute("aria-invalid", "true");

    const group = field.closest(".device-form-group");

    if (!group) {
        return;
    }

    const error = document.createElement("small");
    error.className = "field-error";
    error.textContent = message;
    group.appendChild(error);
}


function validateDeviceForm() {
    clearDeviceFieldErrors();

    const errors = [];
    const field = (id) => document.getElementById(id);

    function requireText(id, message) {
        const input = field(id);

        if (!input.value.trim()) {
            errors.push({ input, message });
        }
    }

    function requireInteger(id, min, max, message) {
        const input = field(id);
        const value = Number(input.value);

        if (
            input.value.trim() === ""
            || !Number.isInteger(value)
            || value < min
            || value > max
        ) {
            errors.push({ input, message });
        }
    }

    requireText(
        "new-device-key",
        "Cihaz anahtarı boş bırakılamaz."
    );
    requireText(
        "new-device-name",
        "Cihaz adı boş bırakılamaz."
    );
    requireInteger(
        "new-device-unit-id",
        1,
        247,
        "Unit ID 1 ile 247 arasında tam sayı olmalı."
    );

    const protocol = field("new-device-protocol").value;

    if (protocol === "tcp") {
        requireText(
            "new-device-host",
            "TCP cihazı için host adresi gerekli."
        );
        requireInteger(
            "new-device-port",
            1,
            65535,
            "TCP portu 1 ile 65535 arasında olmalı."
        );
    }

    if (protocol === "rtu") {
        const transport = field("new-device-transport").value;

        if (transport === "serial") {
            requireText(
                "new-device-serial-port",
                "Gerçek RTU cihazı için COM portu gerekli."
            );
            requireInteger(
                "new-device-baudrate",
                1,
                Number.MAX_SAFE_INTEGER,
                "Baudrate sıfırdan büyük bir tam sayı olmalı."
            );
            requireInteger(
                "new-device-bytesize",
                5,
                8,
                "Bytesize 5 ile 8 arasında olmalı."
            );
        }
    }

    const rows = [
        ...document.querySelectorAll(
            "#measurement-list [data-measurement-row]"
        )
    ];

    rows.forEach((row, index) => {
        const measurementNumber = index + 1;
        const measurementField = (name) => row.querySelector(
            `[data-field="${name}"]`
        );

        function requireMeasurementText(name, message) {
            const input = measurementField(name);

            if (!input.value.trim()) {
                errors.push({ input, message });
            }
        }

        function requireMeasurementInteger(
            name,
            min,
            max,
            message
        ) {
            const input = measurementField(name);
            const value = Number(input.value);

            if (
                input.value.trim() === ""
                || !Number.isInteger(value)
                || value < min
                || value > max
            ) {
                errors.push({ input, message });
            }
        }

        requireMeasurementText(
            "key",
            `Ölçüm ${measurementNumber}: Ölçüm anahtarı gerekli.`
        );
        requireMeasurementText(
            "name",
            `Ölçüm ${measurementNumber}: Ölçüm adı gerekli.`
        );
        requireMeasurementInteger(
            "address",
            0,
            65535,
            `Ölçüm ${measurementNumber}: Register adresi 0 ile 65535 arasında olmalı.`
        );
        requireMeasurementInteger(
            "count",
            1,
            125,
            `Ölçüm ${measurementNumber}: Register adedi 1 ile 125 arasında olmalı.`
        );
        requireMeasurementText(
            "unit",
            `Ölçüm ${measurementNumber}: Birim gerekli.`
        );

        const dataType = measurementField("data_type").value;
        const count = Number(measurementField("count").value);

        if (
            dataType === "u32"
            && Number.isInteger(count)
            && count !== 2
        ) {
            errors.push({
                input: measurementField("count"),
                message: "U32 veri tipi için register adedi 2 olmalı."
            });
        }

        const scaleInput = measurementField("scale");
        const scale = Number(scaleInput.value);

        if (
            scaleInput.value.trim() === ""
            || !Number.isFinite(scale)
            || scale <= 0
        ) {
            errors.push({
                input: scaleInput,
                message: "Scale sıfırdan büyük bir sayı olmalı."
            });
        }
    });

    if (!errors.length) {
        return true;
    }

    errors.forEach(
        ({ input, message }) => setDeviceFieldError(input, message)
    );
    setDeviceFormFeedback(
        "Lütfen işaretli alanları düzeltin.",
        "is-error"
    );
    errors[0].input.focus();
    return false;
}


function highlightDeviceServerError(message) {
    const normalizedMessage = String(message)
        .toLocaleLowerCase("tr-TR");

    if (normalizedMessage.includes("unit id tekrar ediyor")) {
        setDeviceFieldError(
            document.getElementById("new-device-unit-id"),
            "Bu Unit ID başka bir cihazda kullanılıyor."
        );
    }

    if (normalizedMessage.includes("cihaz key değeri tekrar ediyor")) {
        setDeviceFieldError(
            document.getElementById("new-device-key"),
            "Bu cihaz anahtarı zaten kullanılıyor."
        );
    }
}


function setupDeviceForm() {
    const form = document.getElementById(
        "device-form"
    );

    const saveButton = document.getElementById(
        "save-device"
    );

    if (!form || !saveButton) {
        return;
    }

    form.addEventListener(
        "input",
        (event) => {
            clearDeviceFieldError(event.target);
            markDeviceFormDirty();
        }
    );
    form.addEventListener(
        "change",
        (event) => {
            clearDeviceFieldError(event.target);
            markDeviceFormDirty();
        }
    );

    form.addEventListener(
        "submit",
        async (event) => {
            event.preventDefault();

            if (!validateDeviceForm()) {
                return;
            }

            const isEditing = Boolean(editingDeviceKey);
            const requestUrl = isEditing
                ? `/api/devices/${encodeURIComponent(editingDeviceKey)}`
                : "/api/devices";
            const requestMethod = isEditing
                ? "PATCH"
                : "POST";
            const deviceData = collectDeviceFormData();

            saveButton.disabled = true;
            saveButton.textContent = isEditing
                ? "Güncelleniyor..."
                : "Kaydediliyor...";
            setDeviceFormFeedback(
                "Bilgiler kontrol ediliyor..."
            );

            try {
                const response = await fetch(
                    requestUrl,
                    {
                        method: requestMethod,
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify(
                            deviceData
                        )
                    }
                );

                const result = await response.json();

                if (!response.ok) {
                    highlightDeviceServerError(
                        result.error || "Cihaz kaydedilemedi."
                    );
                    throw new Error(
                        result.error || "Cihaz kaydedilemedi."
                    );
                }

                resetDeviceForm();
                const hasMeasurements = deviceData.measurements.length > 0;
                setDeviceFormFeedback(
                    isEditing
                        ? (
                            hasMeasurements
                                ? "Cihaz ve ölçümleri başarıyla güncellendi."
                                : "Cihaz başarıyla güncellendi. Ölçümler daha sonra eklenebilir."
                        )
                        : (
                            hasMeasurements
                                ? "Cihaz ve ölçümleri başarıyla kaydedildi."
                                : "Cihaz başarıyla kaydedildi. Ölçümler daha sonra eklenebilir."
                        ),
                    "is-success"
                );

                await loadManagedDevices();
                await refreshReadings();
            } catch (error) {
                setDeviceFormFeedback(
                    `Cihaz kaydedilemedi: ${error.message}`,
                    "is-error"
                );
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = editingDeviceKey
                    ? "Güncellemeyi kaydet"
                    : "Kaydet";
            }
        }
    );
}


function setupCsvImport() {
    const form = document.getElementById(
        "csv-import-form"
    );
    const devicesFileInput = document.getElementById(
        "csv-devices-file"
    );
    const measurementsFileInput = document.getElementById(
        "csv-measurements-file"
    );
    const autoUnitIdsInput = document.getElementById(
        "csv-auto-unit-ids"
    );
    const feedback = document.getElementById(
        "csv-import-feedback"
    );
    const preview = document.getElementById(
        "csv-import-preview"
    );
    const submitButton = document.getElementById(
        "preview-csv-import"
    );
    const saveButton = document.getElementById(
        "save-csv-import"
    );

    if (
        !form
        || !devicesFileInput
        || !measurementsFileInput
        || !autoUnitIdsInput
        || !feedback
        || !preview
        || !submitButton
        || !saveButton
    ) {
        return;
    }

    form.addEventListener(
        "submit",
        async (event) => {
            event.preventDefault();

            const devicesFile = devicesFileInput.files[0];
            const measurementsFile = measurementsFileInput.files[0];

            if (!devicesFile || !measurementsFile) {
                feedback.textContent =
                    "Cihaz ve ölçüm CSV dosyalarını seçin.";
                feedback.className = "device-form-feedback is-error";
                preview.hidden = true;
                return;
            }

            const formData = new FormData();
            formData.append(
                "devices_file",
                devicesFile
            );
            formData.append(
                "measurements_file",
                measurementsFile
            );
            formData.append(
                "auto_unit_ids",
                autoUnitIdsInput.checked ? "true" : "false"
            );

            submitButton.disabled = true;
            submitButton.textContent = "CSV dosyaları kontrol ediliyor...";
            saveButton.hidden = true;
            feedback.textContent = "CSV dosyaları okunuyor...";
            feedback.className = "device-form-feedback";
            preview.hidden = true;

            try {
                const response = await fetch(
                    "/api/devices/import-preview",
                    {
                        method: "POST",
                        body: formData
                    }
                );
                const result = await response.json();

                if (!response.ok) {
                    const details = Array.isArray(
                        result.details
                    )
                        ? result.details.join("\n\n")
                        : result.details || result.error;

                    throw new Error(
                        details || "CSV doğrulaması başarısız."
                    );
                }

                feedback.textContent =
                    `${result.device_count} cihaz ve ${result.measurement_count} ölçüm doğrulandı. Henüz kaydedilmedi.`;
                feedback.className = "device-form-feedback is-success";
                preview.replaceChildren();

                const previewTitle = document.createElement(
                    "strong"
                );
                previewTitle.textContent = "Önizleme";
                preview.appendChild(previewTitle);

                const previewList = document.createElement(
                    "ul"
                );

                for (const device of result.devices) {
                    const item = document.createElement(
                        "li"
                    );
                    item.textContent =
                        `${device.name} · ${device.protocol.toUpperCase()} · Unit ID ${device.unit_id} · ${device.measurement_count} ölçüm`;
                    previewList.appendChild(item);
                }

                preview.appendChild(previewList);
                preview.hidden = false;
                saveButton.hidden = false;
            } catch (error) {
                feedback.textContent =
                    `CSV doğrulaması başarısız: ${error.message}`;
                feedback.className = "device-form-feedback is-error";
                saveButton.hidden = true;
            } finally {
                submitButton.disabled = false;
                submitButton.textContent = "CSV dosyalarını kontrol et";
            }
        }
    );

    saveButton.addEventListener(
        "click",
        async () => {
            const devicesFile = devicesFileInput.files[0];
            const measurementsFile = measurementsFileInput.files[0];

            if (!devicesFile || !measurementsFile) {
                feedback.textContent =
                    "Kayıt için iki CSV dosyasını da seçin.";
                feedback.className = "device-form-feedback is-error";
                saveButton.hidden = true;
                return;
            }

            const formData = new FormData();
            formData.append(
                "devices_file",
                devicesFile
            );
            formData.append(
                "measurements_file",
                measurementsFile
            );
            formData.append(
                "auto_unit_ids",
                autoUnitIdsInput.checked ? "true" : "false"
            );

            saveButton.disabled = true;
            saveButton.textContent = "SQLite’a kaydediliyor...";
            feedback.textContent =
                "Dosyalar tekrar doğrulanıyor ve kaydediliyor...";
            feedback.className = "device-form-feedback";

            try {
                const response = await fetch(
                    "/api/devices/import",
                    {
                        method: "POST",
                        body: formData
                    }
                );
                const result = await response.json();

                if (!response.ok) {
                    const details = Array.isArray(
                        result.details
                    )
                        ? result.details.join("\n\n")
                        : result.details || result.error;

                    throw new Error(
                        details || "CSV kaydı başarısız."
                    );
                }

                feedback.textContent =
                    `${result.device_count} cihaz ve ${result.measurement_count} ölçüm SQLite’a kaydedildi.`;
                feedback.className = "device-form-feedback is-success";
                saveButton.hidden = true;
                preview.hidden = true;
                form.reset();
                await loadManagedDevices();
                await refreshReadings();
            } catch (error) {
                feedback.textContent =
                    `CSV kaydı başarısız: ${error.message}`;
                feedback.className = "device-form-feedback is-error";
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = "Önizlemeyi SQLite’a kaydet";
            }
        }
    );
}


setupDeviceModal();
setupManagedDeviceBulkActions();
setupBulkDeviceForm();
setupCsvImport();


function setupProtocolFields() {
    const protocolSelect = document.getElementById(
        "new-device-protocol"
    );

    const tcpFields = document.getElementById(
        "tcp-fields"
    );

    const rtuFields = document.getElementById(
        "rtu-fields"
    );

    const transportSelect = document.getElementById(
        "new-device-transport"
    );

    const rtuSerialFields = document.getElementById(
        "rtu-serial-fields"
    );

    if (
        !protocolSelect
        || !tcpFields
        || !rtuFields
        || !transportSelect
        || !rtuSerialFields
    ) {
        return;
    }

    function updateProtocolFields() {
        const isTcp = protocolSelect.value === "tcp";

        tcpFields.hidden = !isTcp;
        rtuFields.hidden = isTcp;

        if (isTcp) {
            rtuSerialFields.hidden = true;
        } else {
            updateTransportFields();
        }
    }

    function updateTransportFields() {
        rtuSerialFields.hidden =
            transportSelect.value !== "serial";
    }

    protocolSelect.addEventListener(
        "change",
        updateProtocolFields
    );

    transportSelect.addEventListener(
        "change",
        updateTransportFields
    );

    updateProtocolFields();
}


setupProtocolFields();


function setupMeasurementFields() {
    const measurementList = document.getElementById(
        "measurement-list"
    );

    const addButton = document.getElementById(
        "add-measurement"
    );

    if (!measurementList || !addButton) {
        return;
    }

    const initialRow = measurementList.querySelector(
        "[data-measurement-row]"
    );

    if (!initialRow) {
        return;
    }

    const measurementTemplate = initialRow.cloneNode(true);
    initialRow.remove();

    function getRows() {
        return [
            ...measurementList.querySelectorAll(
                "[data-measurement-row]"
            )
        ];
    }

    function updateRowTitlesAndButtons() {
        const rows = getRows();

        rows.forEach((row, index) => {
            const title = row.querySelector(
                "[data-measurement-title]"
            );

            const removeButton = row.querySelector(
                "[data-remove-measurement]"
            );

            title.textContent = `Ölçüm ${index + 1}`;
            removeButton.disabled = false;
        });
    }

    function updateRegisterCount(row) {
        if (!row) {
            return;
        }

        const dataType = row.querySelector(
            '[data-field="data_type"]'
        );

        const count = row.querySelector(
            '[data-field="count"]'
        );

        count.value = dataType.value === "u32"
            ? "2"
            : "1";
    }

    function clearClonedRow(row) {
        const textFields = [
            "key",
            "name",
            "address",
            "unit"
        ];

        for (const fieldName of textFields) {
            row.querySelector(
                `[data-field="${fieldName}"]`
            ).value = "";
        }

        row.querySelector(
            '[data-field="function_code"]'
        ).value = "3";

        row.querySelector(
            '[data-field="count"]'
        ).value = "1";

        row.querySelector(
            '[data-field="data_type"]'
        ).value = "u16";

        row.querySelector(
            '[data-field="scale"]'
        ).value = "0.1";
    }

    function addMeasurementRow() {
        const firstRow = measurementList.querySelector(
            "[data-measurement-row]"
        );

        const newRow = (firstRow || measurementTemplate).cloneNode(true);

        clearClonedRow(newRow);
        measurementList.appendChild(newRow);
        updateRowTitlesAndButtons();
    }

    addButton.addEventListener(
        "click",
        () => {
            addMeasurementRow();
            markDeviceFormDirty();
        }
    );

    measurementList.addEventListener(
        "change",
        (event) => {
            if (
                event.target.matches(
                    '[data-field="data_type"]'
                )
            ) {
                updateRegisterCount(
                    event.target.closest(
                        "[data-measurement-row]"
                    )
                );
            }
        }
    );

    measurementList.addEventListener(
        "click",
        (event) => {
            const removeButton = event.target.closest(
                "[data-remove-measurement]"
            );

            if (!removeButton) {
                return;
            }

            const row = removeButton.closest(
                "[data-measurement-row]"
            );

            if (!row) {
                return;
            }

            row.remove();

            updateRowTitlesAndButtons();
            markDeviceFormDirty();
        }
    );

    updateRowTitlesAndButtons();
    updateRegisterCount(
        measurementList.querySelector(
            "[data-measurement-row]"
        )
    );
}


setupMeasurementFields();
setupDeviceForm();
