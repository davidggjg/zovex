import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getLegalDocs, getUpdated } from '../config/legal';
import { t, getLanguage, setLanguage } from '../i18n';

// דפי המידע של האתר: אודות, תנאי שימוש, פרטיות, זכויות יוצרים.
// עד עכשיו הם היו קיימים רק באפליקציה — האתר, שהוא הדלת הראשית, לא הציג
// אותם כלל ולא היה אליהם אפילו קישור.
export default function Legal() {
  const docs = getLegalDocs();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const wanted = params.get('doc');
  const [idx, setIdx] = useState(() => {
    const i = docs.findIndex(d => d.key === wanted);
    return i >= 0 ? i : 0;
  });
  const doc = docs[idx] || docs[0];

  const pick = i => {
    setIdx(i);
    setParams({ doc: docs[i].key });   // כתובת שאפשר לשלוח למישהו
  };

  return (
    <div style={{ minHeight: '100vh', background: '#0a0a0a', color: '#e8eaed' }}>
      <header style={{
        position: 'sticky', top: 0, zIndex: 10, padding: '14px 16px',
        background: 'rgba(10,10,10,0.9)', backdropFilter: 'blur(18px)',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <h1 onClick={() => nav('/')}
          style={{ color: '#e50914', fontSize: 22, fontWeight: 900, letterSpacing: 4,
                   margin: 0, cursor: 'pointer' }}>ZOVEX</h1>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => setLanguage(getLanguage() === 'he' ? 'en' : 'he')}
          title={t('common.language')}
          style={{ background: 'rgba(255,255,255,0.06)', color: '#e8eaed',
                   border: '1px solid rgba(255,255,255,0.12)', borderRadius: 50,
                   padding: '8px 13px', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
          {getLanguage() === 'he' ? 'EN' : 'עב'}
        </button>
      </header>

      <div style={{ maxWidth: 820, margin: '0 auto', padding: '18px 16px 60px' }}>
        {/* לשוניות. נגללות לרוחב בנייד במקום להצטמצם לטקסט לא קריא. */}
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 14 }}>
          {docs.map((d, i) => (
            <button key={d.key} onClick={() => pick(i)}
              style={{
                whiteSpace: 'nowrap', cursor: 'pointer', borderRadius: 50,
                padding: '9px 16px', fontSize: 14, fontWeight: 600,
                border: '1px solid ' + (i === idx ? 'transparent' : 'rgba(255,255,255,0.12)'),
                background: i === idx ? '#e50914' : 'rgba(255,255,255,0.05)',
                color: i === idx ? '#fff' : '#c8ccd0',
              }}>{d.tab}</button>
          ))}
        </div>

        <h2 style={{ fontSize: 25, fontWeight: 800, margin: '10px 0 4px' }}>{doc.title}</h2>
        <div style={{ color: '#7c8288', fontSize: 13, marginBottom: 22 }}>
          {getLanguage() === 'he' ? 'עודכן' : 'Updated'}: {getUpdated()}
        </div>

        {doc.sections.map(([heading, paras], i) => (
          <section key={i} style={{ marginBottom: 26 }}>
            <h3 style={{ fontSize: 17, fontWeight: 700, color: '#fff', margin: '0 0 8px' }}>
              {heading}
            </h3>
            {paras.map((p, j) => (
              <p key={j} style={{ fontSize: 15, lineHeight: 1.75, color: '#bdc1c6',
                                  margin: '0 0 10px', whiteSpace: 'pre-line' }}>{p}</p>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
