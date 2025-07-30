function startVoiceCall(recipientId, recipientName) {
    // Show calling UI
    const modal = document.getElementById('chat-modal');
    modal.classList.remove('hidden');
    
    // Create call room
    fetch('/chat/start-call', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            recipient_id: recipientId,
            type: 'audio'
        })
    })
    .then(response => response.json())
    .then(data => {
        // Connect to room using Twilio
        connectToRoom(data.room_name);
    })
    .catch(error => {
        console.error('Error:', error);
        document.getElementById('call-status').innerHTML = `
            <p class="text-red-600">Call failed. Please try again.</p>
        `;
    });
}

function connectToRoom(roomName) {
    // Get Twilio token
    fetch('/chat/token')
        .then(res => res.json())
        .then(data => {
            // Connect to room
            Twilio.Video.connect(data.token, {
                name: roomName,
                audio: true,
                video: false
            }).then(room => {
                // Handle room events
                room.on('participantConnected', participant => {
                    console.log('Participant connected:', participant.identity);
                    
                    participant.tracks.forEach(publication => {
                        if (publication.isSubscribed) {
                            const track = publication.track;
                            document.getElementById('remote-audio').appendChild(track.attach());
                        }
                    });
                });
                
                room.on('disconnected', room => {
                    console.log('Disconnected from room');
                    document.getElementById('chat-modal').classList.add('hidden');
                });
            });
        });
}