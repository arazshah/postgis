"""رله NTRIP: محافظت SSRF، تحلیل sourcetable و رله واقعی روی یک کستر ساختگی محلی."""
import socket
import threading
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from survey import ntrip

GGA = "$GNGGA,092750.000,5321.6802,N,00630.3372,W,1,8,1.03,61.7,M,55.2,M,,*76"
TABLE = ("SOURCETABLE 200 OK\r\nServer: x\r\n\r\nCAS;a;2101;x;y;0;IRN;;0;0\r\n"
         "STR;MP1;Tehran;RTCM 3.2;1004(1);2;GPS+GLO;SNIP;IRN;35.7;51.4;1;0;x;none;B;N;9600;\r\n"
         "STR;MP2;Qom;RTCM 3.0;1004(1);2;GPS;SNIP;IRN;34.6;50.8;0;0;x;none;B;N;9600;\r\n"
         "ENDSOURCETABLE\r\n")


class FakeCaster:
    """کستر ساده: درخواست را می‌خواند، ‹ICY 200 OK› و چند بایت RTCM می‌فرستد و GGA دریافتی را ثبت می‌کند."""

    def __init__(self, reply=b"ICY 200 OK\r\n\r\n", payload=b"\xd3\x00\x13RTCM", table=False, chunked=False):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(2)
        self.port = self.srv.getsockname()[1]
        self.reply, self.payload, self.table, self.chunked = reply, payload, table, chunked
        self.requests, self.received = [], b""
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    def _serve(self):
        try:
            c, _ = self.srv.accept()
        except OSError:
            return
        c.settimeout(2)
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += c.recv(1024)
        self.requests.append(buf.decode("latin-1"))
        if self.table:
            c.sendall(TABLE.encode())
            c.close()
            return
        if self.chunked:
            c.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
            c.sendall(b"%x\r\n%s\r\n" % (len(self.payload), self.payload))
            c.sendall(b"0\r\n\r\n")
        else:
            c.sendall(self.reply + self.payload)
        if self.reply.startswith(b"ICY") and not self.chunked:
            try:
                while True:
                    d = c.recv(1024)
                    if not d:
                        break
                    self.received += d
            except OSError:
                pass
        c.close()

    def close(self):
        self.srv.close()


class StubSession:
    def __init__(self, gga=""):
        self.pk, self.gga = "00000000-0000-0000-0000-000000000000", gga


class Profile:
    def __init__(self, port, mount="MP1", host="127.0.0.1"):
        self.host, self.port, self.mountpoint, self.username, self.tls, self.send_gga = host, port, mount, "u", False, True


class SsrfTests(SimpleTestCase):
    def test_private_and_special_addresses_are_blocked(self):
        for ip in ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.9", "169.254.169.254", "0.0.0.0", "::1", "fd00::1",
                   "::ffff:127.0.0.1"]:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            with mock.patch("socket.getaddrinfo", return_value=[(fam, 1, 6, "", (ip, 2101))]):
                with self.assertRaises(ntrip.NtripError, msg=ip):
                    ntrip.resolve_public("caster.example", 2101)

    def test_mixed_answers_with_one_private_address_are_blocked(self):
        infos = [(socket.AF_INET, 1, 6, "", ("8.8.8.8", 2101)), (socket.AF_INET, 1, 6, "", ("10.0.0.1", 2101))]
        with mock.patch("socket.getaddrinfo", return_value=infos), self.assertRaises(ntrip.NtripError):
            ntrip.resolve_public("rebind.example", 2101)

    def test_public_address_is_accepted(self):
        with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, 1, 6, "", ("8.8.8.8", 2101))]):
            self.assertEqual(ntrip.resolve_public("caster.example", 2101), (socket.AF_INET, "8.8.8.8"))

    def test_connect_uses_the_checked_ip_not_the_name(self):
        with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, 1, 6, "", ("8.8.8.8", 2101))]), \
                mock.patch("socket.socket") as s:
            ntrip._connect("caster.example", 2101, False, 3)
        s.return_value.connect.assert_called_once_with(("8.8.8.8", 2101))

    def test_request_line_injection_is_rejected(self):
        for kw in [dict(host="a.com\r\nX: y"), dict(mountpoint="a b"), dict(mountpoint="a\r\nHost: evil"),
                   dict(username="u:v"), dict(password="p\r\n"), dict(port=0), dict(port=70000), dict(host="a/b")]:
            args = dict(host="a.com", port=2101, mountpoint="MP", username="u", password="p") | kw
            with self.assertRaises(ntrip.NtripError, msg=str(kw)):
                ntrip.validate_profile(**args)


class ParseTests(SimpleTestCase):
    def test_sourcetable(self):
        rows = ntrip.parse_sourcetable(TABLE)
        self.assertEqual([r["mountpoint"] for r in rows], ["MP1", "MP2"])
        self.assertTrue(rows[0]["needs_gga"])
        self.assertFalse(rows[1]["needs_gga"])
        self.assertEqual(rows[0]["lat"], 35.7)

    def test_gga_whitelist(self):
        self.assertTrue(ntrip.GGA_RE.match(GGA))
        self.assertFalse(ntrip.GGA_RE.match("$GPGGA,1\r\nGET /evil"))
        self.assertFalse(ntrip.GGA_RE.match("GET / HTTP/1.1"))


@override_settings(NTRIP_ALLOW_PRIVATE=True)
class RelayTests(TestCase):
    def setUp(self):
        self.addCleanup(lambda: [c.close() for c in getattr(self, "casters", [])])
        self.casters = []

    def caster(self, **kw):
        c = FakeCaster(**kw)
        self.casters.append(c)
        return c

    def test_sourcetable_fetch(self):
        c = self.caster(table=True)
        rows = ntrip.fetch_sourcetable("127.0.0.1", c.port, False, "u", "p")
        self.assertEqual(len(rows), 2)
        self.assertIn("Authorization: Basic dTpw", c.requests[0])

    def test_wrong_credentials_message(self):
        c = self.caster(reply=b"HTTP/1.1 401 Unauthorized\r\n\r\n", payload=b"")
        with self.assertRaisesMessage(ntrip.NtripError, "گذرواژه"):
            ntrip.open_relay(StubSession(), Profile(c.port), "p")

    def test_unknown_mountpoint_returns_sourcetable_and_is_rejected(self):
        c = self.caster(reply=b"SOURCETABLE 200 OK\r\n\r\n", payload=b"STR;x\r\nENDSOURCETABLE\r\n")
        with self.assertRaises(ntrip.NtripError):
            ntrip.open_relay(StubSession(), Profile(c.port), "p")

    def test_slot_released_after_failure(self):
        c = self.caster(reply=b"HTTP/1.1 401 x\r\n\r\n", payload=b"")
        before = ntrip._slots._value
        self.addCleanup(lambda: self.assertEqual(ntrip._slots._value, before))
        with self.assertRaises(ntrip.NtripError):
            ntrip.open_relay(StubSession(), Profile(c.port), "p")

    def test_empty_mountpoint_is_refused(self):
        with self.assertRaises(ntrip.NtripError):
            ntrip.open_relay(StubSession(), Profile(1, mount=""), "p")

    def test_stream_delivers_rtcm_and_releases_slot(self):
        c = self.caster()
        before = ntrip._slots._value
        with mock.patch.object(ntrip.Relay, "_poll", lambda self: None):
            relay = ntrip.open_relay(StubSession(GGA), Profile(c.port), "p")
            self.assertEqual(ntrip._slots._value, before - 1)
            got = b""
            for chunk in relay:
                got += chunk
                if len(got) >= len(c.payload):
                    break
            relay.close()
        self.assertEqual(got, b"\xd3\x00\x13RTCM")
        self.assertEqual(ntrip._slots._value, before)
        self.assertIn("GET /MP1 HTTP/1.1", c.requests[0])
        self.assertIn(GGA, c.requests[0])  # GGA اولیه همراه درخواست رفت
