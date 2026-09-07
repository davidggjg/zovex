// המימוש האמיתי של MediaFetcher — משיכת בייטים מטלגרם דרך upload.GetFile
// גולמי (לא דרך חבילת downloader הגבוהה של gotd/td, כי היא לא תומכת ב-
// offset/limit חלקי בגרסה הזו — וזה בדיוק מה שדרוש כדי לתמוך ב-Range,
// seek, והמשך צפייה. זה תואם למה שהקוד הפייתוני הקיים כבר עושה ידנית).
//
// ✅  נבדק בפועל מול טלגרם אמיתי (2026-09-06): לוקי S1E1 נמשך בשלמותו
// (1.28GB, אומת כ-MP4 תקין). הדרישה שהתגלתה בבדיקה: access_hash הוא
// ספציפי לחשבון המבקש — בוט אחד לא יכול להשתמש ב-access_hash של בוט אחר
// (מחזיר CHANNEL_INVALID). לכן כל botClient מחזיק את ה-channel שלו עצמו
// (ר' pool.go), ואותו בוט משמש גם לפתרון ההודעה וגם למשיכת כל הבייטים
// שלה — לא מתחלפים באמצע (ייתכן שגם ה-file reference רגיש לאותו הדבר).
package main

import (
	"context"
	"fmt"
	"net/http"

	"github.com/gotd/td/tg"
)

// גודל קטע משיכה — חייב להיות כפולה של 4096 (דרישת טלגרם ל-offset/limit).
// 1MB תואם למה שכבר נמדד ועובד טוב בצד הפייתוני (PYROGRAM_CHUNK_SIZE-style).
const fetchChunkSize = 1024 * 1024

type TelegramFetcher struct {
	pool *Pool
}

func NewTelegramFetcher(pool *Pool) *TelegramFetcher {
	return &TelegramFetcher{pool: pool}
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

func (f *TelegramFetcher) GetInfo(chatID, messageID int64) (*MediaInfo, error) {
	doc, _, err := f.resolveDocument(context.Background(), messageID)
	if err != nil {
		return nil, err
	}
	fileName := ""
	for _, a := range doc.Attributes {
		if fn, ok := a.(*tg.DocumentAttributeFilename); ok {
			fileName = fn.FileName
		}
	}
	return &MediaInfo{FileSize: doc.Size, MimeType: doc.MimeType, FileName: fileName}, nil
}

func (f *TelegramFetcher) Stream(chatID, messageID int64, r byteRange, w http.ResponseWriter) error {
	ctx := context.Background()
	doc, bc, err := f.resolveDocument(ctx, messageID)
	if err != nil {
		return err
	}
	loc := &tg.InputDocumentFileLocation{
		ID:            doc.ID,
		AccessHash:    doc.AccessHash,
		FileReference: doc.FileReference,
		ThumbSize:     "",
	}

	// מיישרים למטה לגבול הקטע (טלגרם דורש offset מיושר), ומשליכים את
	// הבייטים העודפים בתחילת הקטע הראשון בלבד.
	alignedStart := (r.start / fetchChunkSize) * fetchChunkSize
	skip := r.start - alignedStart
	offset := alignedStart
	remaining := r.end - r.start + 1
	first := true

	for remaining > 0 {
		// אותו בוט בדיוק שפתר את ההודעה — לא מתחלפים באמצע.
		res, err := bc.api.UploadGetFile(ctx, &tg.UploadGetFileRequest{
			Location: loc,
			Offset:   offset,
			Limit:    fetchChunkSize,
		})
		if err != nil {
			return fmt.Errorf("UploadGetFile נכשל ב-offset %d (בוט %s): %w", offset, bc.name, err)
		}
		uf, ok := res.(*tg.UploadFile)
		if !ok {
			return fmt.Errorf("סוג קובץ לא נתמך (%T) — כנראה הפניית CDN, עוד לא ממומש", res)
		}
		data := uf.Bytes
		if len(data) == 0 {
			break // קצה הקובץ
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
		offset += fetchChunkSize
	}
	return nil
}
