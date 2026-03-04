const chatBox = document.getElementById('chatBox');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const urlInput = document.getElementById('urlInput');
const ingestBtn = document.getElementById('ingestBtn');
const ingestStatus = document.getElementById('ingestStatus');

// --- THE AMNESIA FIX ---
// This array permanently stores the chat context while the page is open.
let conversationHistory = [];
const CUSTOMER_ID = "demo_user_01";

// --- 1. CHAT LOGIC ---
async function sendMessage() {
    const question = chatInput.value.trim();
    if (!question) return;

    // 1. Display user message in UI
    appendMessage(question, 'user');
    chatInput.value = '';

    // 2. Show loading animation
    const loadingId = appendMessage('Searching vector database...', 'assistant', true);

    try {
        // 3. Send the question AND the history to the backend
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: question,
                customer_id: CUSTOMER_ID,
                history: conversationHistory
            })
        });

        const data = await response.json();
        
        // Remove loading animation
        document.getElementById(loadingId).remove();

        if (response.ok) {
            // Display the AI's answer
            appendMessage(data.answer, 'assistant');
            
            // --- SAVE TO MEMORY ---
            // Push both interactions into the array so the next question has context
            conversationHistory.push({ role: 'user', content: question });
            conversationHistory.push({ role: 'assistant', content: data.answer });
        } else {
            appendMessage(`System Error: ${data.detail}`, 'assistant');
        }
    } catch (error) {
        document.getElementById(loadingId).remove();
        appendMessage('Fatal Error: Could not connect to the Axiora-AI Engine.', 'assistant');
    }
}

// Helper function to build the chat bubbles
function appendMessage(text, sender, isLoading = false) {
    const msgDiv = document.createElement('div');
    const id = 'msg-' + Date.now();
    msgDiv.id = id;
    
    if (sender === 'user') {
        msgDiv.className = 'bg-blue-600 text-white self-end p-4 rounded-lg rounded-tr-none max-w-[80%] shadow-md';
    } else {
        msgDiv.className = 'bg-slate-200 text-slate-800 self-start p-4 rounded-lg rounded-tl-none max-w-[80%] shadow-sm border border-slate-300 leading-relaxed';
        if (isLoading) msgDiv.classList.add('animate-pulse');
    }
    
    // Convert markdown linebreaks to HTML
    const formattedText = text.replace(/\n/g, '<br>');
    msgDiv.innerHTML = `<p>${formattedText}</p>`;
    
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
    
    return id;
}

// --- 2. DATA INGESTION LOGIC ---
async function ingestUrl() {
    const url = urlInput.value.trim();
    if (!url) return;

    ingestBtn.disabled = true;
    ingestBtn.innerText = 'Processing...';
    ingestStatus.classList.remove('hidden');
    ingestStatus.innerHTML = `<span class="text-blue-600 animate-pulse">Launching headless browser and chunking markdown data...</span>`;

    try {
        const response = await fetch(`/api/ingest?url=${encodeURIComponent(url)}&customer_id=${CUSTOMER_ID}`, {
            method: 'POST'
        });

        const data = await response.json();

        if (response.ok) {
            ingestStatus.innerHTML = `<span class="text-emerald-600 font-bold">✅ Success!</span><br><span class="text-slate-600">${data.chunks_saved_to_db} chunks vectorized and saved to Pinecone.</span>`;
            urlInput.value = '';
        } else {
            ingestStatus.innerHTML = `<span class="text-red-600 font-bold">❌ Error:</span> ${data.detail}`;
        }
    } catch (error) {
        ingestStatus.innerHTML = `<span class="text-red-600 font-bold">❌ Connection Error</span>`;
    }

    ingestBtn.disabled = false;
    ingestBtn.innerText = 'Ingest Data';
}

// --- EVENT LISTENERS ---
sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});
ingestBtn.addEventListener('click', ingestUrl);