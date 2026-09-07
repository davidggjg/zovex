package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"testing"
)

// החתימה חייבת להיות זהה לזו שבפייתון, אחרת 8,682 הקישורים החתומים
// שכבר יושבים בקטלוג יפסיקו לעבוד ברגע המעבר. הווקטורים כאן חושבו
// בנפרד עם hmac/hashlib של פייתון על אותה סכמה:
//
//	hmac.new(SECRET, f"{chat}/{msg}/{exp}", sha256).hexdigest()[:32]
func TestStreamSigMatchesPython(t *testing.T) {
	const secret = "zovex-test-secret"
	cases := []struct {
		chat, msg string
		exp       int64
		want      string
	}{
		{"-1003936100530", "9138", 1788801300, "37828e8c5bf33a1372c0c766c1425d75"},
		{"-1001234567890", "1", 0, "7413b6b397d7dccceac415fadf753b44"},
	}
	for _, c := range cases {
		got := streamSig(secret, c.chat, c.msg, c.exp)
		if len(got) != 32 {
			t.Fatalf("אורך החתימה %d, ציפינו 32", len(got))
		}
		if got != c.want {
			t.Errorf("streamSig(%s/%s/%d) = %s, פייתון נותנת %s",
				c.chat, c.msg, c.exp, got, c.want)
		}
	}
}

func TestVerifySigRejectsExpired(t *testing.T) {
	const secret = "s"
	sig := streamSig(secret, "1", "2", 1)
	if verifySig(secret, "1", "2", 1, sig) {
		t.Error("חתימה שפג תוקפה התקבלה")
	}
	if !verifySig("", "1", "2", 1, "כל דבר") {
		t.Error("בלי סוד צריך לעבור, כמו בפייתון")
	}
}

func TestParseRange(t *testing.T) {
	const size = 1000
	tests := []struct {
		in                 string
		wantOK             bool
		wantStart, wantEnd int64
	}{
		{"bytes=0-99", true, 0, 99},
		{"bytes=100-", true, 100, 999},
		{"bytes=-200", true, 800, 999},
		{"bytes=0-99999", true, 0, 999}, // נחתך לגודל הקובץ
		{"bytes=900-100", false, 0, 0},  // התחלה אחרי הסוף
		{"items=0-1", false, 0, 0},
		{"bytes=abc-1", false, 0, 0},
	}
	for _, tc := range tests {
		got, ok := parseRange(tc.in, size)
		if ok != tc.wantOK {
			t.Errorf("%q: ok=%v ציפינו %v", tc.in, ok, tc.wantOK)
			continue
		}
		if ok && (got.start != tc.wantStart || got.end != tc.wantEnd) {
			t.Errorf("%q: קיבלנו %d-%d ציפינו %d-%d",
				tc.in, got.start, got.end, tc.wantStart, tc.wantEnd)
		}
	}
}

// ── בדיקת המשיכה המקדימה ────────────────────────────────────────────────

// fakeMedia מחקה קובץ בגודל ידוע שבו כל בייט הוא (offset mod 251). זה
// מאפשר לוודא שהבייטים יצאו **לפי הסדר** ובדיוק בטווח שהתבקש — הסכנה
// האמיתית במשיכה מקבילה היא שקטעים יגיעו מעורבבים.
type fakeMedia struct {
	size  int64
	calls chan int64
}

func (f *fakeMedia) Info() MediaInfo { return MediaInfo{FileSize: f.size} }

func (f *fakeMedia) Stream(ctx context.Context, r byteRange, w io.Writer) error {
	return streamWithPrefetch(ctx, r, w, func(ctx context.Context, off int64) ([]byte, error) {
		if f.calls != nil {
			f.calls <- off
		}
		if off >= f.size {
			return nil, nil
		}
		n := int64(fetchChunkSize)
		if off+n > f.size {
			n = f.size - off
		}
		b := make([]byte, n)
		for i := range b {
			b[i] = byte((off + int64(i)) % 251)
		}
		return b, nil
	})
}

func wantByte(off int64) byte { return byte(off % 251) }

func TestStreamPrefetchKeepsOrderAndRange(t *testing.T) {
	const size = int64(fetchChunkSize)*5 + 1234
	f := &fakeMedia{size: size}

	for _, r := range []byteRange{
		{0, size - 1}, // הקובץ כולו
		{fetchChunkSize + 7, fetchChunkSize*3 + 9}, // טווח לא מיושר, כמו seek
		{size - 10, size - 1},                      // הזנב
		{5, 5},                                     // בייט בודד
	} {
		var buf bytes.Buffer
		if err := f.Stream(context.Background(), r, &buf); err != nil {
			t.Fatalf("טווח %d-%d: %v", r.start, r.end, err)
		}
		want := r.end - r.start + 1
		if int64(buf.Len()) != want {
			t.Fatalf("טווח %d-%d: קיבלנו %d בייט, ציפינו %d",
				r.start, r.end, buf.Len(), want)
		}
		for i, got := range buf.Bytes() {
			if exp := wantByte(r.start + int64(i)); got != exp {
				t.Fatalf("טווח %d-%d: בייט %d = %d, ציפינו %d (סדר התערבב?)",
					r.start, r.end, i, got, exp)
			}
		}
	}
}

func TestStreamStopsWhenViewerLeaves(t *testing.T) {
	f := &fakeMedia{size: int64(fetchChunkSize) * 500}
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // הצופה עזב עוד לפני שהתחלנו

	err := f.Stream(ctx, byteRange{0, f.size - 1}, io.Discard)
	if err == nil {
		t.Fatal("ציפינו שהמשיכה תיעצר כשה-ctx בוטל")
	}
}

func TestStreamPropagatesChunkError(t *testing.T) {
	boom := fmt.Errorf("טלגרם נפלה")
	err := streamWithPrefetch(context.Background(), byteRange{0, fetchChunkSize * 3},
		io.Discard, func(ctx context.Context, off int64) ([]byte, error) {
			if off >= fetchChunkSize*2 {
				return nil, boom
			}
			return make([]byte, fetchChunkSize), nil
		})
	if err == nil {
		t.Fatal("שגיאה בקטע צריכה להיכשל את הבקשה, לא להיבלע")
	}
}
