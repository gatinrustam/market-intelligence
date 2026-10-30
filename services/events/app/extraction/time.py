import re
from datetime import date

MONTHS={m.lower():i+1 for i,m in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'))}
MONTH_PATTERN=re.compile(r'\b('+'|'.join(MONTHS)+r')\s+(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?,?\s+(\d{4})\b',re.I)
ISO_PATTERN=re.compile(r'\b\d{4}-\d{2}-\d{2}\b')


def extract_title_time(title):
    values=[]
    try:
        for match in MONTH_PATTERN.finditer(title):
            start=date(int(match[4]),MONTHS[match[1].lower()],int(match[2]))
            if match[3]:
                end=date(start.year,start.month,int(match[3]))
                if end<start:
                    return None,'unknown','not_extracted'
                values.append((f'{start.isoformat()}/{end.isoformat()}','date_range','title'))
            else:
                values.append((start.isoformat(),'date','title'))
        for match in ISO_PATTERN.finditer(title):
            values.append((date.fromisoformat(match[0]).isoformat(),'date','title'))
    except ValueError:
        return None,'unknown','not_extracted'
    # Multiple dates are ambiguous; never infer which one is the actual event date.
    return values[0] if len(values)==1 else (None,'unknown','not_extracted')
