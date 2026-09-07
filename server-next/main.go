// zovex-server-next: פרויקט צד, לא מחובר לשרת החי.
//
// שלב 1 (זה): שלד שרת ה-HTTP + אימות חתימת /stream, תואם ביט-לביט לסכימה
// הקיימת ב-main.py (_stream_sig): HMAC-SHA256 על "{chat}/{msg}/{exp}",
// חתוך ל-32 תווי hex ראשונים. זה מאפשר לקישורים חתומים שכבר קיימים
// בקטלוג הנוכחי לעבוד בלי לשנות אותם, ברגע שהשרת הזה יחליף את הישן.
//
// MediaFetcher מומש בפועל ב-telegram_fetcher.go; ה-stub כאן נשאר רק כדי
// שהשרת יעלה ויענה גם בלי טוקנים מוגדרים (למשל בבדיקת חתימות בלבד).
package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

// ── חתימת קישורים: זהה ל-_stream_sig ב-main.py ──────────────────────────────

func streamSig(secret, chat, msg string, exp int64) string {
	data := fmt.Sprintf("%s/%s/%d", chat, msg, exp)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(data))
	full := hex.EncodeToString(mac.Sum(nil))
	return full[:32]
}

func verifySig(secret, chat, msg string, exp int64, sig string) bool {
	if secret == "" {
		return true // תואם להתנהגות main.py: בלי SIGN_SECRET, אין אימות
	}
	if exp < time.Now().Unix() {
		return false
	}
	want := streamSig(secret, chat, msg, exp)
	return subtle.ConstantTimeCompare([]byte(sig), []byte(want)) == 1
}

// ── טווח בקשה (Range: bytes=start-end) ──────────────────────────────────────

type byteRange struct{ start, end int64 } // כולל שני הקצוות, כמו HTTP Range

func parseRange(header string, fileSize int64) (byteRange, bool) {
	if !strings.HasPrefix(header, "bytes=") {
		return byteRange{}, false
	}
	spec := strings.TrimPrefix(header, "bytes=")
	parts := strings.SplitN(spec, "-", 2)
	if len(parts) != 2 {
		return byteRange{}, false
	}
	var start, end int64
	var err error
	if parts[0] == "" {
		// "-500" = 500 הבייטים האחרונים
		n, e := strconv.ParseInt(parts[1], 10, 64)
		if e != nil {
			return byteRange{}, false
		}
		start = fileSize - n
		end = fileSize - 1
	} else {
		start, err = strconv.ParseInt(parts[0], 10, 64)
		if err != nil {
			return byteRange{}, false
		}
		if parts[1] == "" {
			end = fileSize - 1
		} else {
			end, err = strconv.ParseInt(parts[1], 10, 64)
			if err != nil {
				return byteRange{}, false
			}
		}
	}
	if start < 0 {
		start = 0
	}
	if end >= fileSize {
		end = fileSize - 1
	}
	if start > end {
		return byteRange{}, false
	}
	return byteRange{start, end}, true
}

// ── ממשק המשיכה מטלגרם ──────────────────────────────────────────────────────

type MediaInfo struct {
	FileSize int64
	MimeType string
	FileName string
}

type MediaFetcher interface {
	GetInfo(chatID, messageID int64) (*MediaInfo, error)
	// Stream כותב את הבייטים [r.start, r.end] (כולל) אל w.
	Stream(chatID, messageID int64, r byteRange, w http.ResponseWriter) error
}

type stubFetcher struct{}

func (stubFetcher) GetInfo(chatID, messageID int64) (*MediaInfo, error) {
	return nil, fmt.Errorf("MediaFetcher לא מחובר עדיין לטלגרם — שלב הבא")
}

func (stubFetcher) Stream(chatID, messageID int64, r byteRange, w http.ResponseWriter) error {
	return fmt.Errorf("MediaFetcher לא מחובר עדיין לטלגרם — שלב הבא")
}

// ── /stream/{chat_id}/{message_id} ──────────────────────────────────────────

type server struct {
	signSecret string
	fetcher    MediaFetcher
}

func (s *server) handleStream(w http.ResponseWriter, r *http.Request) {
	// path: /stream/{chat_id}/{message_id}
	parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
	if len(parts) != 3 {
		http.NotFound(w, r)
		return
	}
	chatStr, msgStr := parts[1], parts[2]
	chatID, err1 := strconv.ParseInt(chatStr, 10, 64)
	messageID, err2 := strconv.ParseInt(msgStr, 10, 64)
	if err1 != nil || err2 != nil {
		http.Error(w, "bad ids", http.StatusBadRequest)
		return
	}

	q := r.URL.Query()
	exp, _ := strconv.ParseInt(q.Get("exp"), 10, 64)
	sig := q.Get("sig")
	if !verifySig(s.signSecret, chatStr, msgStr, exp, sig) {
		http.Error(w, "הקישור פג תוקף או חתימה שגויה", http.StatusForbidden)
		return
	}

	info, err := s.fetcher.GetInfo(chatID, messageID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusServiceUnavailable)
		return
	}

	rangeHeader := r.Header.Get("Range")
	if rangeHeader == "" {
		w.Header().Set("Accept-Ranges", "bytes")
		w.Header().Set("Content-Length", strconv.FormatInt(info.FileSize, 10))
		w.Header().Set("Content-Type", info.MimeType)
		w.WriteHeader(http.StatusOK)
		if err := s.fetcher.Stream(chatID, messageID, byteRange{0, info.FileSize - 1}, w); err != nil {
			log.Printf("⛔  Stream נכשל באמצע (chat=%d msg=%d): %v", chatID, messageID, err)
		}
		return
	}

	rng, ok := parseRange(rangeHeader, info.FileSize)
	if !ok {
		http.Error(w, "טווח לא תקין", http.StatusRequestedRangeNotSatisfiable)
		return
	}
	w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", rng.start, rng.end, info.FileSize))
	w.Header().Set("Accept-Ranges", "bytes")
	w.Header().Set("Content-Length", strconv.FormatInt(rng.end-rng.start+1, 10))
	w.Header().Set("Content-Type", info.MimeType)
	w.WriteHeader(http.StatusPartialContent)
	if err := s.fetcher.Stream(chatID, messageID, rng, w); err != nil {
		log.Printf("⛔  Stream נכשל באמצע (chat=%d msg=%d, range=%d-%d): %v", chatID, messageID, rng.start, rng.end, err)
	}
}

func buildFetcher(ctx context.Context) MediaFetcher {
	tokens := strings.Split(os.Getenv("BOT_TOKENS"), ",")
	apiID, _ := strconv.Atoi(os.Getenv("API_ID"))
	apiHash := os.Getenv("API_HASH")
	channelID, _ := strconv.ParseInt(os.Getenv("STREAM_CHANNEL_ID"), 10, 64)
	// access_hash הוא ספציפי לכל בוט (נמדד בפועל — לא ניתן לשיתוף), לכן
	// רשימה אחת-לאחת מול BOT_TOKENS, לא ערך יחיד: STREAM_CHANNEL_ACCESS_HASHES
	// (ברבים) עם פסיקים, באותו סדר כמו BOT_TOKENS.
	hashStrs := strings.Split(os.Getenv("STREAM_CHANNEL_ACCESS_HASHES"), ",")

	if apiID == 0 || apiHash == "" || tokens[0] == "" || channelID == 0 {
		log.Println("⚠️  BOT_TOKENS/API_ID/API_HASH/STREAM_CHANNEL_ID לא מוגדרים — רץ עם stub (בלי טלגרם אמיתי)")
		return stubFetcher{}
	}
	if len(hashStrs) != len(tokens) {
		log.Fatalf("STREAM_CHANNEL_ACCESS_HASHES (%d ערכים) לא תואם ל-BOT_TOKENS (%d ערכים)",
			len(hashStrs), len(tokens))
	}
	accessHashes := make([]int64, len(hashStrs))
	for i, s := range hashStrs {
		h, err := strconv.ParseInt(strings.TrimSpace(s), 10, 64)
		if err != nil {
			log.Fatalf("STREAM_CHANNEL_ACCESS_HASHES[%d]=%q לא מספר תקין: %v", i, s, err)
		}
		accessHashes[i] = h
	}
	pool, err := NewPool(ctx, apiID, apiHash, tokens, channelID, accessHashes)
	if err != nil {
		log.Fatalf("בניית בריכת בוטים נכשלה: %v", err)
	}
	log.Printf("בריכת בוטים חיה: %d בוטים", pool.Len())
	return NewTelegramFetcher(pool)
}

func main() {
	ctx := context.Background()
	s := &server{
		signSecret: os.Getenv("STREAM_SIGN_SECRET"),
		fetcher:    buildFetcher(ctx),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/stream/", s.handleStream)

	addr := os.Getenv("LISTEN_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	log.Printf("zovex-server-next (שלב 1: שלד + חתימות) מאזין על %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
