var pc = null;
let isNegotiating = false;

function negotiate() {
    return pc.createOffer()
        .then(offer => pc.setLocalDescription(offer))
        .then(() => waitForIceComplete(pc))
        .then(() => {
            return fetch('/offer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(pc.localDescription)
            });
        })
        .then(res => res.json())
        .then(answer => {
            document.getElementById('sessionid').value = answer.sessionid;
            return pc.setRemoteDescription(answer);
        });
}

function waitForIceComplete(pc) {
    return new Promise(resolve => {
        if (pc.iceGatheringState === 'complete') resolve();
        else pc.addEventListener('icegatheringstatechange', () => {
            if (pc.iceGatheringState === 'complete') resolve();
        });
    });
}

function start() {
    if (isNegotiating) return;
    isNegotiating = true;

    const config = {
        sdpSemantics: 'unified-plan',
        iceServers: [{ urls: ['stun:stun.l.google.com:19302'] }]
    };

    pc = new RTCPeerConnection(config);

    // 只加一次
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });

    pc.addEventListener('track', (evt) => {
        if (evt.track.kind === 'video') {
            document.getElementById('video').srcObject = evt.streams[0];
        } else {
            document.getElementById('audio').srcObject = evt.streams[0];
        }
    });

    negotiate().finally(() => {
        isNegotiating = false;
    });
}

function stop() {
    document.getElementById('stop').style.display = 'none';

    // close peer connection
    setTimeout(() => {
        pc.close();
    }, 500);
}

window.onunload = function(event) {
    // 在这里执行你想要的操作
    setTimeout(() => {
        pc.close();
    }, 500);
};

window.onbeforeunload = function (e) {
        setTimeout(() => {
                pc.close();
            }, 500);
        e = e || window.event
        // 兼容IE8和Firefox 4之前的版本
        if (e) {
          e.returnValue = '关闭提示'
        }
        // Chrome, Safari, Firefox 4+, Opera 12+ , IE 9+
        return '关闭提示'
      }