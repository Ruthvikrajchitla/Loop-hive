// LoopHive - Dashboard Interactive Scripting

document.addEventListener("DOMContentLoaded", () => {
    console.log("LoopHive Swarm Dashboard script loaded.");

    // Auto-refresh stats using HTMX-like polling fallback if HTMX isn't fully active
    setInterval(() => {
        updateStats();
    }, 30000);
});

async function updateStats() {
    try {
        const response = await fetch("/api/stats");
        if (response.ok) {
            const data = await response.json();
            
            // Update UI elements if they exist
            const revEl = document.getElementById("total-revenue");
            if (revEl) {
                revEl.textContent = data.total_revenue;
            }
        }
    } catch (e) {
        console.error("Failed to fetch stats update:", e);
    }
}
