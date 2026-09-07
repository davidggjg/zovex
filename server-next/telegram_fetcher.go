// המימוש האמיתי של MediaFetcher — משיכת בייטים מטלגרם דרך upload.GetFile
// גולמי (לא דרך חבילת downloader הגבוהה של gotd/td, כי היא לא תומכת ב-
// offset/limit חלקי בגרסה הזו — וזה בדיוק מה שדרוש כדי לתמוך ב-Range,
// seek, והמשך צפייה. זה תואם למה שהקוד הפייתוני הקיים כבר עושה ידנית).
//
// ✅  נבדק בפועל מול טלגרם אמיתי (2026-09-06): לוקי S1E1 נמשך בשלמותו
// (1.28GB, אומת כ-MP4 תקין), ו-15 צופים במקביל על שלושה בוטים בלי תקיעה.
//
// הדרישה שהתגלתה בבדיקה: access_hash הוא ספציפי לחשבון המבקש — בוט אחד
// לא יכול להשתמש ב-access_hash של בוט אחר (מחזיר CHANNEL_INVALID). לכן כל
// botClient מחזיק את ה-channel שלו עצמו (ר' pool.go), ואותו בוט משמש גם
// לפתרון ההודעה וגם למשיכת כל הבייטים שלה — לא מתחלפים באמצע.
//
// ## משיכה מקדימה (prefetch) — למה זה כאן
//
// הגרסה הראשונה משכה קטע, חיכתה, כתבה לצופה, ואז ביקשה את הבא. כלומר
// בכל קטע יש הלוך-חזור מלא לטלגרם שבו הנגן **לא מקבל כלום**. זה בדיוק
// המקום שבו נוצרת תקיעה באמצע: אם ההלוך-חזור מתארך, החוצץ של הנגן מתרוקן.
//
// כאן מורצות כמה משיכות במקביל, והתוצאות נמסרות **לפי הסדר** — כך שבזמן
// שקטע N נכתב לרשת, קטעים N+1..N+k כבר בדרך. זה אותו תיקון ש-
// TG-FileStreamBot הוסיפו ב-v3.2.0 ("concurrent prefetching ... and retry
// controls") אחרי שעברו ל-Go, והוא לא היה כאן.
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"strconv"
	"time"

	"github.com/gotd/td/tg"
	"github.com/gotd/td/tgerr"
)

// גודל קטע משיכה — חייב להיות כפולה של 4096 (דרישת טלגרם ל-offset/limit).
// 1MB תואם למה שכבר נמדד ועובד טוב בצד הפייתוני (PYROGRAM_CHUNK_SIZE-style).
const fetchChunkSize = 1024 * 1024

// כמה קטעים מותר שיהיו באוויר בו-זמנית. 4 × 1MB = 4MB לצופה במצב הגרוע,
// וזה גם התקרה של הזיכרון לכל סטרים. אפשר לכוון ב-STREAM_PREFETCH.
var prefetchDepth = envInt("STREAM_PREFETCH", 4)

// כמה ניסיונות חוזרים לקטע בודד לפני שמוותרים על הבקשה כולה.
var maxChunkRetries = envInt("STREAM_CHUNK_RETRIES", 3)

func envInt(name string, def int) int {
	if v, err := strconv.Atoi(os.Getenv(name)); err == nil && v > 0 {
		return v
	}
	return def
}

// errCDNRedirect — טלגרם מפנה לשרת CDN במקום להגיש בעצמו. קורה על קבצים
// גדולים באזורים מסוימים. פענוח CDN דורש AES-CTR ו-reupload token ולא
// מומש כאן; הבדיקות מול הערוץ שלנו לא נתקלו בזה. השגיאה נפרדת בכוונה
// כדי שנזהה בלוג אם זה כן קורה בייצור, במקום להתבלבל עם שגיאה אחרת.
var errCDNRedirect = errors.New("טלגרם הפנתה ל-CDN — לא ממומש")

// normalizeChannelID ממיר את צורת ה-Bot API (-100 ואז מזהה הערוץ) למזהה
// ה-MTProto הגולמי. הקטלוג שלנו שומר את הצורה הראשונה — למשל
// -1003936100530 עבור הערוץ 3936100530 — ואילו tg.InputChannel רוצה
// את השנייה. גם צורה גולמית מתקבלת, כדי שהגדרה ידנית לא תישבר.
func normalizeChannelID(chatID int64) int64 {
	const botAPIPrefix = -1000000000000
	if chatID < botAPIPrefix {
		return botAPIPrefix - chatID
	}
	if chatID < 0 {
		return -chatID
	}
	return chatID
}

type TelegramFetcher struct {
	pool *Pool
}

func NewTelegramFetcher(pool *Pool) *TelegramFetcher {
	return &TelegramFetcher{pool: pool}
}

// telegramMedia הוא קובץ שכבר נפתר: המסמך, והבוט שפתר אותו. שמירת שניהם
// יחד היא מה שמונע פתירה שנייה מיותרת בכל בקשה — ומה שמבטיח שאותו בוט
// ימשוך את כל הבייטים.
type telegramMedia struct {
	f         *TelegramFetcher
	info      MediaInfo
	doc       *tg.Document
	bot       *botClient
	messageID int64
}

func (m *telegramMedia) Info() MediaInfo { return m.info }

// ErrWrongChannel — הבקשה מבקשת צ'אט שהשרת הזה לא משרת.
//
// חובה לבדוק את זה: resolveDocument משתמש ב-channel שמוגדר ב-env ומתעלם
// לגמרי מה-chatID שבכתובת. בלי הבדיקה, בקשה ל-/stream/123/456 הייתה
// מחזירה את הודעה 456 **מהערוץ שלנו** — כלומר קובץ אחר לגמרי, בשקט
// ובקוד 200. בקטלוג יש 8,682 פריטים בערוץ הזה ועוד שניים בצ'אטים
// פרטיים, ואלה השניים שהיו נשברים כך.
var ErrWrongChannel = errors.New("הצ'אט המבוקש אינו הערוץ שהשרת הזה משרת")

// Open פותר את ההודעה **פעם אחת** ומחזיר ידית לשימוש חוזר.
func (f *TelegramFetcher) Open(ctx context.Context, chatID, messageID int64) (Media, error) {
	// בקטלוג ה-chat_id מופיע בצורת -100<channelID>, שזו הצורה של Bot API.
	if normalizeChannelID(chatID) != f.pool.channelID {
		return nil, ErrWrongChannel
	}
	doc, bc, err := f.resolveDocument(ctx, messageID)
	if err != nil {
		return nil, err
	}
	fileName := ""
	for _, a := range doc.Attributes {
		if fn, ok := a.(*tg.DocumentAttributeFilename); ok {
			fileName = fn.FileName
		}
	}
	return &telegramMedia{
		f:         f,
		info:      MediaInfo{FileSize: doc.Size, MimeType: doc.MimeType, FileName: fileName},
		doc:       doc,
		bot:       bc,
		messageID: messageID,
	}, nil
}

// resolveDocument בוחר בוט מהבריכה ופותר איתו את ההודעה. מחזיר גם את הבוט
// שנבחר, כדי שהקורא ימשיך להשתמש **באותו בוט בדיוק** למשיכת הבייטים.
func (f *TelegramFetcher) resolveDocument(ctx context.Context, messageID int64) (*tg.Document, *botClient, error) {
	bc := f.pool.Next()
	res, err := bc.api.ChannelsGetMessages(ctx, &tg.ChannelsGetMessagesRequest{
		Channel: bc.channel, // ה-access_hash הספציפי לבוט הזה, לא ערך משותף
		ID:      []tg.InputMessageClass{&tg.InputMessageID{ID: int(messageID)}},
	})
	if err != nil {
		return nil, nil, fmt.Errorf("ChannelsGetMessages נכשל (בוט %s): %w", bc.name, err)
	}
	var msgs []tg.MessageClass
	switch v := res.(type) {
	case *tg.MessagesChannelMessages:
		msgs = v.Messages
	case *tg.MessagesMessages:
		msgs = v.Messages
	default:
		return nil, nil, fmt.Errorf("סוג תשובה לא צפוי: %T", res)
	}
	if len(msgs) == 0 {
		return nil, nil, fmt.Errorf("הודעה %d לא נמצאה", messageID)
	}
	msg, ok := msgs[0].(*tg.Message)
	if !ok {
		return nil, nil, fmt.Errorf("הודעה %d אינה הודעת תוכן רגילה", messageID)
	}
	media, ok := msg.GetMedia()
	if !ok {
		return nil, nil, fmt.Errorf("אין מדיה בהודעה %d", messageID)
	}
	mmd, ok := media.(*tg.MessageMediaDocument)
	if !ok {
		return nil, nil, fmt.Errorf("המדיה בהודעה %d אינה מסמך", messageID)
	}
	docClass, ok := mmd.GetDocument()
	if !ok {
		return nil, nil, fmt.Errorf("אין document בהודעה %d", messageID)
	}
	doc, ok := docClass.(*tg.Document)
	if !ok {
		return nil, nil, fmt.Errorf("document ריק/לא זמין בהודעה %d", messageID)
	}
	return doc, bc, nil
}

func (m *telegramMedia) location() *tg.InputDocumentFileLocation {
	return &tg.InputDocumentFileLocation{
		ID:            m.doc.ID,
		AccessHash:    m.doc.AccessHash,
		FileReference: m.doc.FileReference,
		ThumbSize:     "",
	}
}

// fetchChunk מושך קטע אחד, עם טיפול בשלוש התקלות שקורות בפועל:
//
//   - FLOOD_WAIT — טלגרם אומרת במפורש כמה לחכות. מכבדים ומנסים שוב.
//   - FILE_REFERENCE_EXPIRED — ההפניה שקיבלנו בפתירה התיישנה (קורה על
//     קבצים שיושבים שעות). הפתרון היחיד הוא לפתור את ההודעה מחדש; רק
//     ה-FileReference מתעדכן, המסמך והבוט נשארים.
//   - שגיאות רשת חולפות — ניסיון חוזר עם השהיה עולה.
//
// בלי זה, כל אחת מהשלוש הפילה את **כל** הבקשה, והצופה ראה תקיעה.
func (m *telegramMedia) fetchChunk(ctx context.Context, offset int64) ([]byte, error) {
	var lastErr error
	for attempt := 0; attempt <= maxChunkRetries; attempt++ {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		res, err := m.bot.api.UploadGetFile(ctx, &tg.UploadGetFileRequest{
			Location: m.location(),
			Offset:   offset,
			Limit:    fetchChunkSize,
		})
		if err == nil {
			switch uf := res.(type) {
			case *tg.UploadFile:
				return uf.Bytes, nil
			case *tg.UploadFileCDNRedirect:
				return nil, errCDNRedirect
			default:
				return nil, fmt.Errorf("סוג תשובה לא נתמך: %T", res)
			}
		}
		lastErr = err

		if d, ok := tgerr.AsFloodWait(err); ok {
			log.Printf("⏳ FLOOD_WAIT %s (בוט %s, offset %d)", d, m.bot.name, offset)
			select {
			case <-time.After(d):
				continue
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
		if tgerr.Is(err, "FILE_REFERENCE_EXPIRED") {
			log.Printf("♻️  file reference פג להודעה %d — פותרים מחדש", m.messageID)
			doc, _, rerr := m.f.resolveDocument(ctx, m.messageID)
			if rerr != nil {
				return nil, fmt.Errorf("פתירה מחדש נכשלה: %w", rerr)
			}
			m.doc.FileReference = doc.FileReference
			continue
		}
		if attempt < maxChunkRetries {
			back := time.Duration(1<<attempt) * 250 * time.Millisecond
			select {
			case <-time.After(back):
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
	}
	return nil, fmt.Errorf("offset %d נכשל אחרי %d ניסיונות (בוט %s): %w",
		offset, maxChunkRetries+1, m.bot.name, lastErr)
}

type chunkResult struct {
	data []byte
	err  error
}

// Stream כותב את [r.start, r.end] אל w, עם משיכה מקדימה מקבילה ומסירה
// לפי הסדר. ctx מגיע מהבקשה — כשהצופה עוזב או קופץ, הכל נעצר מיד ולא
// ממשיך למשוך מטלגרם לחינם. זה היה הבאג המרכזי בגרסה הראשונה.
func (m *telegramMedia) Stream(ctx context.Context, r byteRange, w io.Writer) error {
	return streamWithPrefetch(ctx, r, w, m.fetchChunk)
}

// chunkFetcher מושך את הקטע שמתחיל ב-offset. מופרד מ-telegramMedia כדי
// שאפשר יהיה לבדוק את צנרת המשיכה המקדימה בלי טלגרם — הסיכון האמיתי
// במקביליות הוא שקטעים ייכתבו לא לפי הסדר, וזה בדיוק מה שנבדק.
type chunkFetcher func(ctx context.Context, offset int64) ([]byte, error)

func streamWithPrefetch(ctx context.Context, r byteRange, w io.Writer, fetch chunkFetcher) error {
	// מיישרים למטה לגבול הקטע (טלגרם דורש offset מיושר), ומשליכים את
	// הבייטים העודפים בתחילת הקטע הראשון בלבד.
	alignedStart := (r.start / fetchChunkSize) * fetchChunkSize
	skip := r.start - alignedStart
	remaining := r.end - r.start + 1

	// results מוגבל ב-prefetchDepth, וזה מה שחוסם את מספר המשיכות באוויר:
	// המפיק לא יכול לפתוח עוד goroutine עד שהצרכן שחרר מקום.
	results := make(chan chan chunkResult, prefetchDepth)

	ctx, cancel := context.WithCancel(ctx)
	defer cancel() // עוצר כל משיכה שעוד באוויר כשיוצאים מכאן

	go func() {
		defer close(results)
		for offset := alignedStart; offset <= r.end; offset += fetchChunkSize {
			// בדיקה מפורשת לפני ה-select: כששני הענפים מוכנים, גו בוחר
			// **אקראית**, ולכן select לבדו לא מבטיח עצירה אחרי ביטול —
			// נתפס בבדיקה חוזרת שנפלה רק לפעמים.
			if ctx.Err() != nil {
				return
			}
			c := make(chan chunkResult, 1)
			select {
			case results <- c:
			case <-ctx.Done():
				return
			}
			go func(off int64, c chan chunkResult) {
				data, err := fetch(ctx, off)
				c <- chunkResult{data, err}
			}(offset, c)
		}
	}()

	first := true
	for c := range results {
		if err := ctx.Err(); err != nil {
			return err // אותו טעם: לא נשענים על אקראיות ה-select
		}
		var res chunkResult
		select {
		case res = <-c:
		case <-ctx.Done():
			return ctx.Err()
		}
		if res.err != nil {
			return res.err
		}
		data := res.data
		if len(data) == 0 {
			return nil // קצה הקובץ
		}
		if first {
			if int64(len(data)) > skip {
				data = data[skip:]
			} else {
				data = nil
			}
			first = false
		}
		if int64(len(data)) > remaining {
			data = data[:remaining]
		}
		if len(data) > 0 {
			if _, err := w.Write(data); err != nil {
				return err // הצופה עזב — לא שגיאה אמיתית
			}
			remaining -= int64(len(data))
		}
		if remaining <= 0 {
			return nil
		}
	}
	// הגענו לכאן כי הערוץ נסגר. שתי סיבות אפשריות, והן לא אותו דבר:
	// המפיק סיים את הטווח, או שהוא נטש בגלל ביטול. בלי הבדיקה הזאת
	// נטישה נראתה כמו הצלחה, והצופה קיבל גוף קטוע עם 200 — בדיוק
	// התקיעה השקטה שאנחנו מנסים להעלים.
	if err := ctx.Err(); err != nil {
		return err
	}
	if remaining > 0 {
		return fmt.Errorf("הזרם נגמר מוקדם — חסרים %d בייט מהטווח %d-%d",
			remaining, r.start, r.end)
	}
	return nil
}
