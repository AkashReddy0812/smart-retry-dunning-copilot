document.addEventListener('DOMContentLoaded', () => {
    fetchSummary();
    fetchComparison();
    fetchEfficiency();
    fetchQueue();

    document.getElementById('refresh-queue').addEventListener('click', fetchQueue);
    
    document.getElementById('lookup-btn').addEventListener('click', () => {
        const txId = document.getElementById('tx-input').value.trim();
        if (txId) fetchTransaction(txId);
    });
    document.getElementById('btn-sim-funds').addEventListener('click', () => runSimulation('funds'));
    document.getElementById('btn-sim-timeout').addEventListener('click', () => runSimulation('timeout'));
    document.getElementById('btn-sim-upi').addEventListener('click', () => runSimulation('upi'));
    document.getElementById('btn-sim-expired').addEventListener('click', () => runSimulation('expired'));
});

// Chart defaults
Chart.defaults.font.family = 'system-ui, -apple-system, sans-serif';
const COLOR_NAIVE = '#9ca3af'; // Grey
const COLOR_SMART = '#2563eb'; // Blue

async function fetchSummary() {
    try {
        // Absolute path from server root
        const response = await fetch('/dashboard/summary');
        if (!response.ok) return;
        const data = await response.json();
        
        console.log("Overall Summary Loaded:", data);
        // Data available here if you want to expand the UI to show total counts later
    } catch (err) {
        console.error("Error fetching summary data:", err);
    }
}

async function fetchComparison() {
    try {
        // Absolute path from server root
        const response = await fetch('/dashboard/comparison');
        if (!response.ok) return;
        const data = await response.json();

        // Render Lift Metrics
        const liftDiv = document.getElementById('lift-metrics');
        liftDiv.innerHTML = `
            <div class="metric-box">
                <div class="metric-value">+${data.improvement.recovery_rate_pp} pp</div>
                <div class="metric-label">Recovery Rate Improvement</div>
            </div>
            <div class="metric-box highlight">
                <div class="metric-value">+${data.improvement.revenue_lift_pct}%</div>
                <div class="metric-label">Revenue Lift</div>
            </div>
        `;

        // Render Recovery Rate Chart
        new Chart(document.getElementById('rateChart'), {
            type: 'bar',
            data: {
                labels: ['Recovery Rate (%)'],
                datasets: [
                    { label: 'Naive Strategy', data: [data.naive.recovery_rate_pct], backgroundColor: COLOR_NAIVE },
                    { label: 'Smart ML Strategy', data: [data.smart.recovery_rate_pct], backgroundColor: COLOR_SMART }
                ]
            },
            options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, max: 100 } } }
        });

        // Render Revenue Chart
        new Chart(document.getElementById('revChart'), {
            type: 'bar',
            data: {
                labels: ['Revenue Recovered (₹)'],
                datasets: [
                    { label: 'Naive Strategy', data: [data.naive.revenue_recovered_inr], backgroundColor: COLOR_NAIVE },
                    { label: 'Smart ML Strategy', data: [data.smart.revenue_recovered_inr], backgroundColor: COLOR_SMART }
                ]
            },
            options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
        });

    } catch (err) {
        console.error("Error fetching comparison data:", err);
    }
}

async function fetchEfficiency() {
    try {
        const response = await fetch('/dashboard/efficiency');
        if (!response.ok) return;
        const data = await response.json();
        
        // Update the main stat
        const mainStat = document.getElementById('wasted-avoided');
        mainStat.innerText = `${data.smart_retries_avoided.toLocaleString()} wasted retry attempts avoided`;
        
        // Update the subtext
        const total = data.retryable_count + data.non_retryable_count;
        const subtext = document.getElementById('efficiency-subtext');
        subtext.innerText = `${data.non_retryable_count.toLocaleString()} failures (${total.toLocaleString()} total) were correctly identified as non-retryable and skipped entirely, instead of being blindly retried 3 times each.`;
        
        // Populate the breakdown list
        const ul = document.getElementById('breakdown-list');
        ul.innerHTML = '';
        for (const [reason, count] of Object.entries(data.non_retryable_breakdown)) {
            // format reason string (e.g., "card_expired" -> "Card Expired")
            const formattedReason = reason.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            ul.innerHTML += `<li><strong>${formattedReason}:</strong> ${count.toLocaleString()}</li>`;
        }
    } catch (err) {
        console.error("Error fetching efficiency data:", err);
    }
}

async function fetchQueue() {
    const tbody = document.getElementById('queue-body');
    try {
        // Absolute path from server root
        const response = await fetch('/dashboard/queue/live');
        const data = await response.json();
        
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">No pending retries in the queue.</td></tr>';
            return;
        }

        tbody.innerHTML = data.map(item => `
            <tr>
                <td><strong>${item.transaction_id}</strong></td>
                <td>${item.failure_reason}</td>
                <td>${item.attempt_number}</td>
                <td>${new Date(item.scheduled_timestamp).toLocaleString()}</td>
                <td><span class="badge">${(item.predicted_success_probability * 100).toFixed(1)}%</span></td>
            </tr>
        `).join('');
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="5">Error loading queue.</td></tr>';
    }
}

async function fetchTransaction(txId) {
    const resultDiv = document.getElementById('tx-result');
    const metaDiv = document.getElementById('tx-meta');
    const timelineDiv = document.getElementById('tx-timeline');
    
    try {
        // Absolute path from server root
        const response = await fetch(`/transactions/${txId}`);
        if (!response.ok) {
            alert(response.status === 404 ? "Transaction not found." : "Error fetching transaction.");
            resultDiv.classList.add('hidden');
            return;
        }
        
        const data = await response.json();
        const tx = data.transaction;
        
        // Populate Meta
        metaDiv.innerHTML = `
            <div><strong>Status:</strong> <span class="status-${tx.current_status}">${tx.current_status.toUpperCase()}</span></div>
            <div><strong>Amount:</strong> ₹${tx.amount_inr.toLocaleString()}</div>
            <div><strong>Original Reason:</strong> ${tx.failure_reason}</div>
            <div><strong>Payment Method:</strong> ${tx.payment_method} (${tx.issuing_bank})</div>
        `;

        // Build Timeline: Combine Events
        const events = [];
        
        // Original Failure Event
        events.push({
            time: new Date(tx.original_timestamp),
            type: 'failure',
            content: `<strong>Original Payment Failed</strong><br>Reason: ${tx.failure_reason}`
        });

        // Retries
        data.retry_attempts.forEach(r => {
            let content = `<strong>Scheduled Retry #${r.attempt_number}</strong><br>`;
            content += `Target time: ${new Date(r.scheduled_timestamp).toLocaleString()}<br>`;
            content += `Predicted success: ${(r.predicted_success_probability * 100).toFixed(1)}%`;
            
            events.push({ time: new Date(r.created_at), type: 'schedule', content: content });
            
            if (r.executed_timestamp && r.outcome) {
                events.push({
                    time: new Date(r.executed_timestamp),
                    type: r.outcome === 'success' ? 'success' : 'failure',
                    content: `<strong>Execution Outcome: ${r.outcome.toUpperCase()}</strong>`
                });
            }
        });

        // Dunning Messages
        data.dunning_messages.forEach(d => {
            events.push({
                time: new Date(d.created_at),
                type: 'email',
                content: `<strong>Communication Sent</strong><br><div class="email-msg">"${d.message_text}"</div>`
            });
        });

        // Sort events chronologically
        events.sort((a, b) => a.time - b.time);

        // Render Timeline
        timelineDiv.innerHTML = events.map(ev => `
            <div class="timeline-event">
                <div class="timeline-point point-${ev.type}"></div>
                <div class="timeline-content">
                    <div class="timeline-date">${ev.time.toLocaleString()}</div>
                    <div class="timeline-body">${ev.content}</div>
                </div>
            </div>
        `).join('');

        resultDiv.classList.remove('hidden');
        fetchExplain(txId);
    } catch (err) {
        console.error(err);
        alert("Error loading transaction data.");
    }
}

// Clean up model feature names for the UI
function formatFeatureName(rawName) {
    const mappings = {
        'is_near_month_boundary': 'Near month boundary (payday proximity)',
        'hours_since_original_failure': 'Hours since original failure',
        'attempt_number': 'Retry attempt number',
        'amount_inr': 'Transaction Amount (₹)',
        'retry_day_of_month': 'Day of the month'
    };
    
    if (mappings[rawName]) return mappings[rawName];
    
    // Fallback for one-hot encoded features like "failure_reason_insufficient_funds"
    if (rawName.startsWith('failure_reason_')) {
        return 'Failure: ' + rawName.replace('failure_reason_', '').replace(/_/g, ' ');
    }
    if (rawName.startsWith('payment_method_')) {
        return 'Method: ' + rawName.replace('payment_method_', '').toUpperCase();
    }
    if (rawName.startsWith('issuing_bank_')) {
        return 'Bank: ' + rawName.replace('issuing_bank_', '').toUpperCase();
    }
    
    return rawName.replace(/_/g, ' ');
}

async function fetchExplain(txId) {
    const container = document.getElementById('tx-explain-container');
    const barsContainer = document.getElementById('tx-explain-bars');
    
    try {
        const response = await fetch(`/transactions/${txId}/explain`);
        if (!response.ok) {
            container.style.display = 'none';
            return;
        }
        
        const data = await response.json();
        
        if (data.length === 0) {
            container.style.display = 'none';
            return;
        }

        // Find max absolute value to scale the bars properly (max width = 100%)
        const maxAbs = Math.max(...data.map(d => Math.abs(d.shap_value)));
        
        barsContainer.innerHTML = data.map(item => {
            const widthPct = Math.max((Math.abs(item.shap_value) / maxAbs) * 100, 2);
            const colorClass = item.direction === 'positive' ? 'shap-bar-pos' : 'shap-bar-neg';
            const sign = item.direction === 'positive' ? '+' : '';
            
            return `
                <div class="shap-row">
                    <div class="shap-label">${formatFeatureName(item.feature)}</div>
                    <div class="shap-track">
                        <div class="shap-bar ${colorClass}" style="width: ${widthPct}%"></div>
                    </div>
                </div>
            `;
        }).join('');
        
        container.style.display = 'block';
    } catch (err) {
        console.error("Error fetching explanation:", err);
        container.style.display = 'none';
    }
}

// --- Simulation Logic ---

async function runSimulation(type) {
    const txId = 'demo-txn-' + Date.now();
    const nowISO = new Date().toISOString();
    
    // Base payload templates
    const templates = {
        'funds': {
            customer_id: "demo-customer", 
            transaction_type: "subscription_renewal", 
            amount_inr: 999.0, 
            payment_method: "UPI", 
            issuing_bank: "HDFC", 
            failure_reason: "insufficient_funds", 
            is_retryable: true
        },
        'timeout': {
            customer_id: "demo-customer", 
            transaction_type: "one_time", 
            amount_inr: 450.0, 
            payment_method: "netbanking", 
            issuing_bank: "SBI", 
            failure_reason: "bank_server_timeout", 
            is_retryable: true
        },
        'upi': {
            customer_id: "demo-customer", 
            transaction_type: "one_time", 
            amount_inr: 250.0, 
            payment_method: "UPI", 
            issuing_bank: "AXIS", 
            failure_reason: "invalid_upi_pin", 
            is_retryable: true
        },
        'expired': {
            customer_id: "demo-customer", 
            transaction_type: "subscription_renewal", 
            amount_inr: 1999.0, 
            payment_method: "card", 
            issuing_bank: "ICICI", 
            failure_reason: "card_expired", 
            is_retryable: false
        }
    };

    const payload = {
        transaction_id: txId,
        original_timestamp: nowISO,
        ...templates[type]
    };

    try {
        const response = await fetch('/simulate/failure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) throw new Error("Simulation request failed");

        // 1. Show Success Message
        const statusDiv = document.getElementById('sim-status');
        statusDiv.innerText = `✅ Simulation triggered! Generated ID: ${txId}`;
        statusDiv.style.opacity = '1';
        
        // Hide message after 5 seconds
        setTimeout(() => { statusDiv.style.opacity = '0'; }, 5000);

        // 2. Auto-refresh Queue
        // Add a slight delay so the background Celery task has time to write the new retry to the DB
        setTimeout(() => {
            fetchQueue();
            fetchSummary(); // Update the overall stats if needed
        }, 1000);

        // 3. Auto-populate Deep Dive and Look Up
        document.getElementById('tx-input').value = txId;
        
        // Again, slight delay to let Celery finish scheduling
        setTimeout(() => {
            fetchTransaction(txId);
            // Scroll down to the result so the user sees it immediately
            document.getElementById('tx-result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 1500);

    } catch (err) {
        console.error(err);
        const statusDiv = document.getElementById('sim-status');
        statusDiv.innerText = `❌ Error: Could not trigger simulation.`;
        statusDiv.style.color = "var(--danger)";
        statusDiv.style.opacity = '1';
    }
}