import type { CVData } from '../api/cv'
import { flattenSkills } from '../api/cv'

// Mirrors templates/cv_base.html's section structure and ordering (no theme
// CSS — this is the operator console's data view, not the recruiter-facing
// themed/print page, which stays on /cv/html).
export default function CvView({ cv }: { cv: CVData }) {
  const flatSkills = flattenSkills(cv.skills)
  const flatAdditionalSkills = flattenSkills(cv.additional_skills)
  const contactParts = [cv.email, cv.phone, cv.telegram, cv.location].filter(Boolean)
  const links = [cv.github, cv.linkedin, ...cv.websites.map((w) => w.url)].filter(Boolean)

  return (
    <article className="cv-view">
      <header>
        <h1>{cv.name}</h1>
        <p className="cv-subtitle">{cv.title}</p>
        <address className="cv-contact-line">
          {contactParts.join(' · ')}
          {links.length > 0 && (
            <>
              <br />
              {links.map((link, i) => (
                <a key={link} href={link} target="_blank" rel="noreferrer">
                  {i > 0 && ' · '}
                  {link}
                </a>
              ))}
            </>
          )}
        </address>
      </header>

      {cv.summary && (
        <section>
          <h2>Summary</h2>
          <p>{cv.summary}</p>
        </section>
      )}

      {flatSkills.length > 0 && (
        <section>
          <h2>Skills</h2>
          <ul className="cv-skill-list">
            {flatSkills.map((skill) => (
              <li key={skill.category}>
                <strong>{skill.category}:</strong> {skill.items.join(', ')}
              </li>
            ))}
          </ul>
        </section>
      )}

      {flatAdditionalSkills.length > 0 && (
        <section>
          <h2>Additional Skills</h2>
          <ul className="cv-skill-list">
            {flatAdditionalSkills.map((skill) => (
              <li key={skill.category}>
                <strong>{skill.category}:</strong> {skill.items.join(', ')}
              </li>
            ))}
          </ul>
        </section>
      )}

      {cv.experience.length > 0 && (
        <section>
          <h2>Experience</h2>
          {cv.experience.map((job) => (
            <article key={`${job.company}-${job.role}-${job.period}`} className="cv-entry">
              <div className="cv-entry-header">
                <h3>{job.role}</h3>
                <time>{job.period}</time>
              </div>
              <div className="cv-entry-org">{job.company}</div>
              {job.tech.length > 0 && <div className="cv-entry-tech">{job.tech.join(', ')}</div>}
              {job.highlights.length > 0 && (
                <ul>
                  {job.highlights.map((highlight) => (
                    <li key={highlight}>{highlight}</li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </section>
      )}

      {cv.projects.length > 0 && (
        <section>
          <h2>Projects</h2>
          {cv.projects.map((project) => (
            <article key={project.name} className="cv-entry">
              <div className="cv-entry-header">
                <h3>{project.name}</h3>
                {project.url && (
                  <a href={project.url} target="_blank" rel="noreferrer">
                    Link
                  </a>
                )}
              </div>
              {project.description && <div className="cv-entry-org">{project.description}</div>}
              {project.tech.length > 0 && <div className="cv-entry-tech">{project.tech.join(', ')}</div>}
            </article>
          ))}
        </section>
      )}

      {cv.certifications.length > 0 && (
        <section>
          <h2>Certifications</h2>
          {cv.certifications.map((cert) => (
            <article key={cert.name} className="cv-entry">
              <div className="cv-entry-header">
                <h3>{cert.name}</h3>
                <time>{cert.date}</time>
              </div>
              <div className="cv-entry-org">{cert.issuer}</div>
            </article>
          ))}
        </section>
      )}

      {cv.publications.length > 0 && (
        <section>
          <h2>Publications</h2>
          {cv.publications.map((pub) => (
            <article key={pub.title} className="cv-entry">
              <div className="cv-entry-header">
                <h3>{pub.title}</h3>
                <time>{pub.year}</time>
              </div>
              <div className="cv-entry-org">{pub.venue}</div>
            </article>
          ))}
        </section>
      )}

      {cv.awards.length > 0 && (
        <section>
          <h2>Awards</h2>
          {cv.awards.map((award) => (
            <article key={award.name} className="cv-entry">
              <div className="cv-entry-header">
                <h3>{award.name}</h3>
                <time>{award.date}</time>
              </div>
              <div className="cv-entry-org">{award.issuer}</div>
            </article>
          ))}
        </section>
      )}

      {cv.volunteering.length > 0 && (
        <section>
          <h2>Volunteering</h2>
          {cv.volunteering.map((vol) => (
            <article key={`${vol.organization}-${vol.role}`} className="cv-entry">
              <div className="cv-entry-header">
                <h3>{vol.role}</h3>
                <time>{vol.period}</time>
              </div>
              <div className="cv-entry-org">{vol.organization}</div>
              {vol.description && <div>{vol.description}</div>}
            </article>
          ))}
        </section>
      )}

      {cv.education.length > 0 && (
        <section>
          <h2>Education</h2>
          {cv.education.map((edu) => (
            <article key={`${edu.institution}-${edu.degree}`} className="cv-entry">
              <div className="cv-entry-header">
                <h3>{edu.degree}</h3>
                <time>{edu.year}</time>
              </div>
              <div className="cv-entry-org">{edu.institution}</div>
            </article>
          ))}
        </section>
      )}

      {cv.languages.length > 0 && (
        <section>
          <h2>Languages</h2>
          <ul className="cv-skill-list">
            {cv.languages.map((lang) => (
              <li key={lang}>{lang}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  )
}
