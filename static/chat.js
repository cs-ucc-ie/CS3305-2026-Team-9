// ===== Chat Widget =====

let chatOpen = false;
let currentFriend = null;
let lastMessageId = 0;
let pollInterval = null;
let badgePollInterval = null;

const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

// === Utility ===
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    const d = new Date(timestamp.replace(' ', 'T'));
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// === Toggle chat open/close ===
function toggleChat() {
    chatOpen = !chatOpen;
    const panel = document.getElementById('chat-panel');
    const toggle = document.getElementById('chat-toggle');

    if (chatOpen) {
        panel.classList.remove('hidden');
        toggle.classList.add('hidden');
        loadFriendsList();
    } else {
        panel.classList.add('hidden');
        toggle.classList.remove('hidden');
        stopMessagePolling();
        showFriendsListView();
    }
}

// === Friends list ===
function loadFriendsList() {
    fetch('/api/chat/friends')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            const container = document.getElementById('chat-friends-container');
            if (!data.friends || data.friends.length === 0) {
                container.innerHTML = '<div class="chat-no-friends">No friends yet.<br>Add friends from your dashboard.</div>';
                return;
            }
            let html = '';
            data.friends.forEach(function(f) {
                const preview = f.last_message ? escapeHtml(f.last_message) : '<em>No messages yet</em>';
                const badge = f.unread_count > 0
                    ? '<div class="chat-friend-unread">' + f.unread_count + '</div>'
                    : '';
                html += '<div class="chat-friend-item" onclick="openConversation(\'' + escapeHtml(f.user_id) + '\')">'
                    + '<div>'
                    + '<div class="chat-friend-name">' + escapeHtml(f.user_id) + '</div>'
                    + '<div class="chat-friend-preview">' + preview + '</div>'
                    + '</div>'
                    + badge
                    + '</div>';
            });
            container.innerHTML = html;
        })
        .catch(function() {});
}

function showFriendsList() {
    showFriendsListView();
    loadFriendsList();
}

function showFriendsListView() {
    document.getElementById('chat-friends-list').classList.remove('hidden');
    document.getElementById('chat-conversation').classList.add('hidden');
    document.getElementById('chat-header-title').textContent = 'Messages';
    currentFriend = null;
    lastMessageId = 0;
    stopMessagePolling();
}

// === Conversation ===
function openConversation(friendId) {
    currentFriend = friendId;
    lastMessageId = 0;
    document.getElementById('chat-friends-list').classList.add('hidden');
    document.getElementById('chat-conversation').classList.remove('hidden');
    document.getElementById('chat-header-title').textContent = friendId;
    document.getElementById('chat-messages').innerHTML = '';
    document.getElementById('chat-input').value = '';
    hideFilePicker();

    loadMessages(false);
    startMessagePolling();
}

function loadMessages(pollOnly) {
    if (!currentFriend) return;

    const url = pollOnly
        ? '/api/chat/messages/' + encodeURIComponent(currentFriend) + '?after=' + lastMessageId
        : '/api/chat/messages/' + encodeURIComponent(currentFriend);

    fetch(url)
        .then(function(r) {
            if (r.status === 403) {
                // No longer friends
                stopMessagePolling();
                const container = document.getElementById('chat-messages');
                container.innerHTML = '<div class="chat-empty">This conversation is no longer available.</div>';
                return null;
            }
            return r.json();
        })
        .then(function(data) {
            if (!data || data.error) return;

            const container = document.getElementById('chat-messages');

            if (!pollOnly && data.messages.length === 0) {
                container.innerHTML = '<div class="chat-empty">No messages yet. Say hello!</div>';
            }

            if (!pollOnly && data.messages.length > 0) {
                container.innerHTML = '';
            }

            data.messages.forEach(function(msg) {
                appendMessage(msg);
            });

            container.scrollTop = container.scrollHeight;

            // Update badge since we read messages
            if (!pollOnly || data.messages.length > 0) {
                updateUnreadBadge();
            }
        })
        .catch(function() {});
}

function appendMessage(msg) {
    const container = document.getElementById('chat-messages');

    // Remove empty state message if present
    const empty = container.querySelector('.chat-empty');
    if (empty) empty.remove();

    const msgEl = document.createElement('div');
    msgEl.className = 'chat-msg ' + (msg.is_mine ? 'chat-msg-mine' : 'chat-msg-theirs');

    let content = '';
    if (msg.file_id) {
        if (msg.file_token && msg.file_name) {
            content += '<div class="chat-msg-file">📎 <a href="/download/' + escapeHtml(msg.file_token) + '">' + escapeHtml(msg.file_name) + '</a></div>';
        } else {
            content += '<div class="chat-msg-file">📎 <em>File no longer available</em></div>';
        }
    }
    if (msg.content) {
        content += '<div>' + escapeHtml(msg.content) + '</div>';
    }
    content += '<div class="chat-msg-time">' + formatTime(msg.timestamp) + '</div>';

    msgEl.innerHTML = content;
    container.appendChild(msgEl);

    if (msg.id > lastMessageId) {
        lastMessageId = msg.id;
    }
}

function startMessagePolling() {
    stopMessagePolling();
    pollInterval = setInterval(function() {
        if (currentFriend) {
            loadMessages(true);
        }
    }, 3000);
}

function stopMessagePolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// === Send message ===
function sendMessage() {
    const input = document.getElementById('chat-input');
    const content = input.value.trim();
    if (!content || !currentFriend) return;

    input.value = '';

    fetch('/api/chat/send', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': CSRF_TOKEN
        },
        body: JSON.stringify({
            receiver_id: currentFriend,
            content: content
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            appendMessage(data.message);
            const container = document.getElementById('chat-messages');
            container.scrollTop = container.scrollHeight;
        }
    })
    .catch(function() {});
}

// === File sharing ===
function showFilePicker() {
    const picker = document.getElementById('chat-file-picker');
    picker.classList.remove('hidden');

    fetch('/api/chat/my-files')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            const select = document.getElementById('chat-file-select');
            select.innerHTML = '<option value="">Select a file...</option>';
            data.files.forEach(function(f) {
                const opt = document.createElement('option');
                opt.value = f.id;
                opt.textContent = f.original_filename;
                select.appendChild(opt);
            });
        })
        .catch(function() {});
}

function hideFilePicker() {
    document.getElementById('chat-file-picker').classList.add('hidden');
}

function sendFile() {
    const select = document.getElementById('chat-file-select');
    const fileId = parseInt(select.value);
    if (!fileId || !currentFriend) return;

    fetch('/api/chat/share-file', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': CSRF_TOKEN
        },
        body: JSON.stringify({
            receiver_id: currentFriend,
            file_id: fileId
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            appendMessage(data.message);
            const container = document.getElementById('chat-messages');
            container.scrollTop = container.scrollHeight;
            hideFilePicker();
        }
    })
    .catch(function() {});
}

// === Unread badge ===
function updateUnreadBadge() {
    fetch('/api/chat/unread-count')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            const badge = document.getElementById('chat-badge');
            if (data.unread_count > 0) {
                badge.textContent = data.unread_count > 99 ? '99+' : data.unread_count;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        })
        .catch(function() {});
}

// Start badge polling on page load
updateUnreadBadge();
badgePollInterval = setInterval(updateUnreadBadge, 10000);
