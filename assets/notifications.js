window.dash_clientside = Object.assign({}, window.dash_clientside, {
    clientside: {
        play_notification: function(data) {
            if (!data || data.length === 0) {
                return '';
            }
            
            // Request permission on first run
            if (window.Notification && Notification.permission !== "granted" && Notification.permission !== "denied") {
                Notification.requestPermission();
            }
            
            // Get the last item in the array
            const lastItem = data[data.length - 1];
            if (lastItem && lastItem.label && window.Notification) {
                const shownKey = 'shown_' + lastItem.key;
                if (!sessionStorage.getItem(shownKey)) {
                    sessionStorage.setItem(shownKey, '1');
                    
                    if (Notification.permission === "granted") {
                        try {
                            new Notification("Quantum HUD Varování", {
                                body: lastItem.label,
                                tag: lastItem.key
                            });
                        } catch (e) {
                            console.error("Failed to show native notification", e);
                        }
                    }
                }
            }
            return '';
        }
    }
});
