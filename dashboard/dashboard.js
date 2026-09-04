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
    } catch (err) {
        console.error(err);
        alert("Error loading transaction data.");
    }
}