import slixmpp

def apply_xmpp_patch():
    original_connect = slixmpp.ClientXMPP.connect

    def patched_connect(self, address=None, *args, **kwargs):
        if address:
            if isinstance(address, tuple):
                kwargs['host'], kwargs['port'] = address
            else:
                kwargs['host'] = address
        return original_connect(self, *args, **kwargs)

    slixmpp.ClientXMPP.connect = patched_connect
