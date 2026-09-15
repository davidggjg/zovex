import {getLanguage} from '../i18n';

// טקסט דפי המידע של האתר.
//
// עותק זהה לזה שבאפליקציה (zovex-android/src/config/legal.js). הכפילות
// מכוונת — שני מאגרים נפרדים, ואי-אפשר לייבא ביניהם — אבל היא מחייבת
// לעדכן את שניהם יחד. נוסח משפטי ששונה בין האתר לאפליקציה גרוע מאין נוסח.
//
// זה נוסח כללי ולא ייעוץ משפטי.

const UPDATED_HE = 'אוגוסט 2026';
const UPDATED_EN = 'August 2026';

const LEGAL_DOCS_HE = [
  {
    key: 'about',
    tab: 'אודות',
    title: 'אודות ZOVEX',
    sections: [
      ['מה זה', [
        'ZOVEX הוא שירות צפייה בעברית בסרטים, סדרות ושידורים חיים, שנבנה ' +
        'כפרויקט אישי ופועל ללא מטרות רווח.',
        'השירות זמין באתר ובאפליקציית אנדרואיד.',
      ]],
      ['מי מפעיל', [
        'צוות קטן של מתנדבים. אין חברה, אין מנוי, אין תשלום — ואף אחד לא ' +
        'מתבקש למסור פרטי אשראי בשום שלב.',
        'אם מישהו פונה אליכם בשם השירות ומבקש תשלום, סיסמה או קוד אימות — ' +
        'זו הונאה. דווחו לנו.',
      ]],
      ['איך פונים אלינו', [
        'בכפתור התמיכה שבאפליקציה, בשרת הדיסקורד, או בערוץ הטלגרם.',
      ]],
    ],
  },
  {
    key: 'terms',
    tab: 'תנאי שימוש',
    title: 'תנאי שימוש',
    sections: [
      ['1 · קבלת התנאים', [
        'השימוש ב-ZOVEX מהווה הסכמה לתנאים האלה. מי שלא מסכים — מתבקש לא ' +
        'להשתמש בשירות.',
        'אנחנו רשאים לעדכן את התנאים; המשך שימוש אחרי עדכון מהווה הסכמה ' +
        'לנוסח המעודכן.',
      ]],
      ['2 · השירות ניתן כמות שהוא', [
        'השירות ניתן ללא תשלום, ללא התחייבות לזמינות, ובלי אחריות מכל סוג. ' +
        'ייתכנו תקלות, הפסקות, תוכן שאינו מתנגן ושינויים בקטלוג ללא הודעה.',
        'איננו אחראים לנזק ישיר או עקיף שייגרם משימוש בשירות או מאי-זמינותו.',
      ]],
      ['3 · שימוש אישי בלבד', [
        'התוכן מיועד לצפייה אישית. אסור להקליט, לשכפל, להפיץ מחדש, למכור או ' +
        'לשדר את התוכן, ואסור לגבות עליו תשלום כלשהו.',
        'אסור לשלב את השירות באפליקציה או באתר אחר, ואסור למכור גישה אליו.',
      ]],
      ['4 · שימוש הוגן במערכת', [
        'אסור להריץ סורקים, בוטים או כלי הורדה המונית, ואסור לנסות לעקוף ' +
        'הגבלות, לחדור למערכות או להעמיס עליהן במכוון.',
        'אסור להשתמש בשירות לכל מטרה בלתי חוקית.',
      ]],
      ['5 · חשבונות והורדות', [
        'התחברות עם גוגל היא רשות, ומטרתה לשמור היסטוריית צפייה והמשך צפייה.',
        'הורדות באפליקציה נשמרות מוצפנות במכשיר, לצפייה במצב לא-מקוון בלבד. ' +
        'אסור לחלץ אותן או להעביר אותן הלאה.',
        'אתם אחראים לפעילות בחשבון שלכם. אנחנו רשאים לחסום גישה למי שמפר את ' +
        'התנאים.',
      ]],
      ['6 · תוכן של צדדים שלישיים', [
        'חלק מהתוכן, מהשידורים החיים ומהתמונות מגיעים ממקורות חיצוניים ' +
        'שאינם בשליטתנו. אנחנו לא אחראים לתוכן, לזמינות או לתנאי השימוש שלהם.',
      ]],
      ['7 · הסרת תוכן', [
        "בעל זכויות שסבור שתוכן מסוים מפר את זכויותיו מוזמן לפנות אלינו — " +
        "ראו 'זכויות יוצרים'.",
      ]],
    ],
  },
  {
    key: 'privacy',
    tab: 'פרטיות',
    title: 'מדיניות פרטיות',
    sections: [
      ['מה אנחנו אוספים', [
        'בלי התחברות: מזהה מכשיר אקראי שנוצר באפליקציה, כדי שהתמיכה תוכל ' +
        'לענות לפנייה שלכם. אין בו שום פרט מזהה.',
        'עם התחברות לגוגל: שם, כתובת אימייל ותמונת פרופיל, כפי שגוגל מוסרת ' +
        'אותם. אנחנו לא מקבלים ולא רואים את הסיסמה שלכם.',
        'היסטוריית צפייה: מה נצפה ובאיזו נקודה עצרתם, כדי לאפשר המשך צפייה. ' +
        'נשמר רק למשתמשים מחוברים.',
        'התראות: אם אישרתם התראות, נשמר מזהה התראות של המכשיר כדי לשלוח ' +
        'עדכונים על תוכן חדש.',
      ]],
      ['מה אנחנו לא עושים', [
        'לא מוכרים ולא מעבירים מידע לצד שלישי.',
        'לא אוספים פרטי תשלום — אין תשלום בשירות.',
        'לא ניגשים לאנשי הקשר, למיקום או לקבצים שלכם.',
      ]],
      ['איפה זה נשמר', [
        'העדפות והורדות נשמרות במכשיר שלכם בלבד. ההורדות מוצפנות.',
        'היסטוריית הצפייה נשמרת בשרת שלנו, מקושרת למזהה החשבון שלכם.',
        'התמונות מגיעות משירותים חיצוניים (למשל TMDB), ולכן הבקשה אליהן ' +
        'נשלחת ישירות מהמכשיר שלכם אליהם.',
      ]],
      ['מחיקה', [
        'יציאה מהחשבון מוחקת את הנתונים המקומיים במכשיר.',
        'למחיקת ההיסטוריה מהשרת — פנו אלינו בתמיכה ונמחק.',
      ]],
      ['קטינים', [
        'השירות אינו מיועד לילדים מתחת לגיל 13, ואיננו אוספים ביודעין מידע ' +
        'עליהם.',
      ]],
    ],
  },
  {
    key: 'copyright',
    tab: 'זכויות יוצרים',
    title: 'זכויות יוצרים והסרת תוכן',
    sections: [
      ['העמדה שלנו', [
        'ZOVEX מכבד זכויות יוצרים. השירות אינו מוכר תוכן ואינו גובה תשלום, ' +
        'ואנחנו מסירים תוכן לפי פנייה של בעל זכויות.',
      ]],
      ['איך מגישים בקשת הסרה', [
        "שלחו אלינו הודעה בערוץ הטלגרם או בשרת הדיסקורד (טיקט מסוג 'דיווח'), " +
        'ובה:',
        '· שם היצירה והקישור המדויק לעמוד אצלנו\n' +
        '· הצהרה שאתם בעל הזכויות או מיופי כוח מטעמו\n' +
        '· פרטי קשר לחזרה\n' +
        '· הצהרה שהפרטים בבקשה נכונים',
      ]],
      ['מה קורה אחר כך', [
        'אנחנו בודקים את הפנייה ומסירים תוכן שנמצא מפר, בדרך כלל תוך ימים ' +
        'בודדים. נעדכן אתכם בתשובה.',
      ]],
      ['קישורים חיצוניים', [
        'שידורים חיים וחלק מהמקורות מתארחים אצל צדדים שלישיים. במקרים כאלה ' +
        'נסיר את ההפניה מצידנו, אך אין לנו שליטה על המקור עצמו.',
      ]],
    ],
  },
];

// ── English ──────────────────────────────────────────────────────────────────
// אותו נוסח באנגלית. הערת הנוסח המחייב נוספת בכוונה: כשמסמך משפטי קיים
// בשתי שפות צריך לומר איזו מהן קובעת, אחרת פער תרגום הופך לוויכוח.

const LEGAL_DOCS_EN = [
  {
    key: 'about',
    tab: 'About',
    title: 'About ZOVEX',
    sections: [
      ['What it is', [
        'ZOVEX is a Hebrew-language service for watching movies, series and live ' +
        'channels. It was built as a personal project and runs on a non-profit basis.',
        'The service is available on the website and as an Android app.',
      ]],
      ['Who runs it', [
        'A small team of volunteers. There is no company, no subscription and no ' +
        'payment — and nobody is ever asked for credit card details.',
        'If someone contacts you in the name of this service and asks for payment, ' +
        'a password or a verification code, it is a scam. Please report it to us.',
      ]],
      ['How to reach us', [
        'Through the support button in the app, the Discord server, or the Telegram channel.',
      ]],
    ],
  },
  {
    key: 'terms',
    tab: 'Terms',
    title: 'Terms of Use',
    sections: [
      ['0 · Language', [
        'This is a translation provided for convenience. The Hebrew version is the ' +
        'binding one; if the two differ, the Hebrew text prevails.',
      ]],
      ['1 · Acceptance', [
        'Using ZOVEX means you accept these terms. If you do not agree, please do ' +
        'not use the service.',
        'We may update these terms; continued use after an update means you accept ' +
        'the updated version.',
      ]],
      ['2 · Provided as is', [
        'The service is free, with no commitment to availability and no warranty of ' +
        'any kind. There may be faults, outages, content that will not play, and ' +
        'catalog changes without notice.',
        'We are not liable for any direct or indirect damage arising from use of the ' +
        'service or from it being unavailable.',
      ]],
      ['3 · Personal use only', [
        'The content is intended for personal viewing. Recording, copying, ' +
        'redistributing, selling or broadcasting the content is not allowed, and it ' +
        'may not be charged for in any way.',
        'The service may not be embedded in another app or website, and access to it ' +
        'may not be sold.',
      ]],
      ['4 · Fair use of the system', [
        'Crawlers, bots and mass-download tools are not allowed. Do not attempt to ' +
        'bypass restrictions, break into systems, or deliberately overload them.',
        'The service may not be used for any unlawful purpose.',
      ]],
      ['5 · Accounts and downloads', [
        'Signing in with Google is optional, and is used to keep your watch history ' +
        'and resume position.',
        'Downloads in the app are stored on your device for offline viewing only, in ' +
        'private app storage. Extracting them or passing them on is not allowed.',
        'You are responsible for activity on your account. We may block access for ' +
        'anyone who breaches these terms.',
      ]],
      ['6 · Third-party content', [
        'Some of the content, live channels and images come from external sources ' +
        'outside our control. We are not responsible for their content, availability ' +
        'or terms of use.',
      ]],
      ['7 · Content removal', [
        'A rights holder who believes content infringes their rights is welcome to ' +
        "contact us — see 'Copyright'.",
      ]],
    ],
  },
  {
    key: 'privacy',
    tab: 'Privacy',
    title: 'Privacy Policy',
    sections: [
      ['What we collect', [
        'Without signing in: a random device identifier generated by the app, so that ' +
        'support can reply to your message. It contains no identifying details.',
        'With Google sign-in: name, email address and profile picture, as provided by ' +
        'Google. We never receive or see your password.',
        'Watch history: what was watched and where you stopped, so you can resume. ' +
        'Stored only for signed-in users.',
        'Notifications: if you allowed notifications, a device notification token is ' +
        'stored so we can send updates about new content.',
      ]],
      ['What we do not do', [
        'We do not sell or pass information to third parties.',
        'We do not collect payment details — the service is free.',
        'We do not access your contacts, location or files.',
      ]],
      ['Where it is stored', [
        'Preferences and downloads are stored on your device only.',
        'Watch history is stored on our server, linked to your account identifier.',
        'Images come from external services (such as TMDB), so the request for them ' +
        'goes directly from your device to them.',
      ]],
      ['Deletion', [
        'Signing out deletes the local data on your device.',
        'To delete your history from the server, contact us through support and we ' +
        'will remove it.',
      ]],
      ['Minors', [
        'The service is not intended for children under 13, and we do not knowingly ' +
        'collect information about them.',
      ]],
    ],
  },
  {
    key: 'copyright',
    tab: 'Copyright',
    title: 'Copyright and Content Removal',
    sections: [
      ['Our position', [
        'ZOVEX respects copyright. The service does not sell content and does not ' +
        'charge for it, and we remove content following a request from a rights holder.',
      ]],
      ['How to submit a removal request', [
        "Send us a message on the Telegram channel or the Discord server (a 'report' " +
        'ticket), including:',
        '· The name of the work and the exact link to the page on our service\n' +
        '· A statement that you are the rights holder or authorised to act for them\n' +
        '· Contact details for our reply\n' +
        '· A statement that the details in the request are accurate',
      ]],
      ['What happens next', [
        'We review the request and remove content found to be infringing, usually ' +
        'within a few days. We will reply to let you know.',
      ]],
      ['External links', [
        'Live channels and some sources are hosted by third parties. In those cases we ' +
        'will remove the reference from our side, but we have no control over the ' +
        'source itself.',
      ]],
    ],
  },
];

// נבחר בזמן קריאה ולא בזמן ייבוא, כדי ששינוי שפה יתפוס בלי הפעלה מחדש.

export function getLegalDocs() {
  return getLanguage() === 'en' ? LEGAL_DOCS_EN : LEGAL_DOCS_HE;
}

export function getUpdated() {
  return getLanguage() === 'en' ? UPDATED_EN : UPDATED_HE;
}
