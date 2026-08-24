CSS = """
/* "original" — paper-CV look (Google Docs export):
   Montserrat hierarchy, centered header with pipe separators,
   blue underlined links, compact single rhythm.
   Structure and geometry live in cv_base.html; this theme only
   sets fonts, sizes and colors.

   Unit system: html font-size anchors the scale at 1rem = 12pt
   (the body text size). Every length is a multiple of that, so
   the whole layout rescales by changing the single value below.
*/

html {
    font-size: 12pt;
}

body {
    font-family: 'Montserrat', 'Liberation Sans', 'DejaVu Sans', Arial, sans-serif;
    font-size: 1rem;              /* 12pt */
    line-height: 1.4;
    color: #000;
}

h1 {
    font-size: 2rem;              /* 24pt */
    font-weight: bold;
    text-align: center;
    line-height: 1.2;
}

.subtitle {
    text-align: center;
    font-size: 1.25rem;           /* 15pt */
    font-weight: bold;
    color: #000;
    line-height: 1.2;
}

.contact-line {
    text-align: center;
    color: #000;
}
.contact-line .sep::before,
.cv-footer .sep::before {
    content: " | ";
}
.contact-line a {
    color: #1155cc;
    text-decoration: underline;
}

h2 {
    font-size: 1.0833rem;         /* 13pt */
    font-weight: bold;
    text-transform: uppercase;
    color: #000;
    border-bottom: none;
    margin-top: 0.8333rem;        /* 10pt breathing unit */
    margin-bottom: 0.8333rem;
}

.skill-category {
    display: block;
}
.skill-text {
    display: block;
}

.job-header {
    align-items: baseline;
}
.job-role {
    font-size: 1.0833rem;         /* 13pt */
    font-weight: bold;
}
.job-company {
    font-style: normal;
}
.job-tech {
    font-size: 1rem;
    color: #000;
}
.job-tech::before {
    content: "Tech: ";
    font-weight: bold;
}
"""
