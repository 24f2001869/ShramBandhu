// shrambandhu/static/js/sos.js (Improved Error Handling)


document.addEventListener('DOMContentLoaded', function() {
    const sosButtons = document.querySelectorAll('[id^="sos-button"]');

    if (sosButtons.length === 0) { return; }

    // --- Get CSRF token from meta tag ---
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    // ------------------------------------

    sosButtons.forEach(button => {
        button.addEventListener('click', async function() {
            console.log("SOS button clicked");
            button.disabled = true;
            button.classList.add('opacity-50', 'cursor-not-allowed');
            showAlert('Requesting location...', 'info', 3000);

            try {
                const position = await getLocation();
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                console.log(`Location obtained: ${lat}, ${lng}`);
                showAlert('Location obtained. Sending SOS...', 'info');

                // --- Include CSRF token in fetch headers ---
                const headers = {
                    'Content-Type': 'application/json'
                };
                if (csrfToken) {
                    headers['X-CSRFToken'] = csrfToken; // Add token if found
                } else {
                    console.warn("CSRF token meta tag not found."); // Warn if missing
                }
                // -------------------------------------------

                const response = await fetch('/worker/sos', {
                    method: 'POST',
                    headers: headers, // Use the headers object
                    body: JSON.stringify({ lat, lng })
                });

                let result;
                try {
                    const contentType = response.headers.get("content-type");
                    if (contentType && contentType.indexOf("application/json") !== -1) {
                        result = await response.json();
                    } else {
                        const textResponse = await response.text();
                        console.error("Received non-JSON response:", response.status, textResponse);
                        // Try to extract a meaningful error from common Flask HTML error pages
                        let htmlErrorMatch = textResponse.match(/<title>(.*?)<\/title>/i);
                        let serverError = htmlErrorMatch ? htmlErrorMatch[1] : `Server returned non-JSON response (Status: ${response.status}). Check server logs.`;
                        throw new Error(serverError);
                    }
                } catch (parseError) {
                     console.error("Error parsing server response:", parseError);
                     throw new Error("Invalid response received from server. Check server logs.");
                }

                if (response.ok && result.success) {
                    console.log("SOS Success Response:", result);
                    showAlert(`SOS sent successfully! Alert ID: ${result.alert_id}. ${result.responders_contacted || 0} responders notified.`, 'success', 10000);
                } else {
                    console.error("SOS Failed Response:", result);
                    throw new Error(result.error || `Failed to send SOS (Status: ${response.status})`);
                }

            } catch (error) {
                console.error('SOS Error:', error);
                showAlert(`SOS failed: ${error.message}`, 'danger', 10000);
            } finally {
                setTimeout(() => {
                    button.disabled = false;
                    button.classList.remove('opacity-50', 'cursor-not-allowed');
                }, 5000);
            }
        });
    });
});

function getLocation() {
    console.log("Attempting to get location...");
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject(new Error('Geolocation not supported by this browser.'));
            return;
        }
        // Added timeout and high accuracy options
        navigator.geolocation.getCurrentPosition(
            resolve,
            (error) => {
                console.error("Geolocation Error:", error);
                let message = 'Could not get location.';
                switch(error.code) {
                    case error.PERMISSION_DENIED: message += " Permission denied."; break;
                    case error.POSITION_UNAVAILABLE: message += " Position unavailable."; break;
                    case error.TIMEOUT: message += " Request timed out."; break;
                    default: message += ` Unknown error (Code ${error.code}).`; break;
                }
                reject(new Error(message));
            },
            {
                enableHighAccuracy: true, // Try for better accuracy
                timeout: 10000, // 10 seconds timeout
                maximumAge: 0 // Force fresh location
            }
        );
    });
}

// Keep monitorSosStatus if implemented previously
// function monitorSosStatus(alertId) { ... }

// Improved showAlert function
let alertTimeoutId = null; // Store timeout ID to clear previous alerts
function showAlert(message, type = 'info', duration = 5000) {
    // Remove existing alert first
    const existingAlert = document.getElementById('dynamic-alert');
    if (existingAlert) {
        clearTimeout(alertTimeoutId); // Clear previous timeout
        existingAlert.remove();
    }

    const alertDiv = document.createElement('div');
    alertDiv.id = 'dynamic-alert'; // Assign an ID for easy removal
    let bgColor, textColor, borderColor;

    switch (type) {
        case 'success': bgColor = 'bg-green-100'; textColor = 'text-green-800'; borderColor = 'border-green-400'; break;
        case 'danger': bgColor = 'bg-red-100'; textColor = 'text-red-800'; borderColor = 'border-red-400'; break;
        case 'warning': bgColor = 'bg-yellow-100'; textColor = 'text-yellow-800'; borderColor = 'border-yellow-400'; break;
        default: bgColor = 'bg-blue-100'; textColor = 'text-blue-800'; borderColor = 'border-blue-400'; type = 'info'; break; // Default to info
    }

    alertDiv.className = `fixed top-5 right-5 p-4 rounded-md shadow-lg border-l-4 ${bgColor} ${textColor} ${borderColor} z-[10000] max-w-sm`; // High z-index
    alertDiv.textContent = message;
    document.body.appendChild(alertDiv);

    // Auto-remove after duration
    alertTimeoutId = setTimeout(() => {
        alertDiv.remove();
    }, duration);
}






function monitorSosStatus(alertId) {
    const interval = setInterval(async () => {
        const response = await fetch(`/worker/sos/status/${alertId}`);
        const status = await response.json();
        
        if (status.status === 'resolved') {
            clearInterval(interval);
            showAlert('Emergency resolved!', 'success');
        }
    }, 5000);
}