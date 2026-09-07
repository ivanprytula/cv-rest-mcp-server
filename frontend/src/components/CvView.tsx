import type { ReactNode } from 'react'
import type { CVData } from '../api/cv'
import { flattenSkills } from '../api/cv'

const skillList = 'my-2 list-disc pl-5'
const section = 'mb-6 max-sm:mb-4'

// One dated/organized item (a job, project, cert, ...) shared by every CV
// section below — same header/org/tech layout, just different content.
function CvEntry({
  title,
  meta,
  org,
  tech,
  children,
}: {
  title: string
  meta?: ReactNode
  org?: string
  tech?: string
  children?: ReactNode
}) {
  return (
    <article className="mb-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="m-0 text-base text-text-h">{title}</h3>
        {meta}
      </div>
      {org && <div className="text-muted">{org}</div>}
      {tech && <div className="text-sm text-muted">{tech}</div>}
      {children}
    </article>
  )
}

// Mirrors templates/cv_base.html's section structure and ordering (no theme
// CSS — this is the operator console's data view, not the recruiter-facing
// themed/print page, which stays on /cv/html).
export default function CvView({ cv }: { cv: CVData }) {
  const flatSkills = flattenSkills(cv.skills)
  const flatAdditionalSkills = flattenSkills(cv.additional_skills)
  const contactParts = [cv.email, cv.phone, cv.telegram, cv.location].filter(Boolean)
  const links = [cv.github, cv.linkedin, ...cv.websites.map((w) => w.url)].filter(Boolean)

  return (
    <article className="max-w-180">
      <header className={section}>
        <h1 className="text-2xl text-text-h">{cv.name}</h1>
        <p>{cv.title}</p>
        <address className="text-muted not-italic">
          {contactParts.join(' · ')}
          {links.length > 0 && (
            <>
              <br />
              {links.map((link, i) => (
                <a key={link} href={link} target="_blank" rel="noreferrer" className="text-accent">
                  {i > 0 && ' · '}
                  {link}
                </a>
              ))}
            </>
          )}
        </address>
      </header>

      {cv.summary && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Summary</h2>
          <p>{cv.summary}</p>
        </section>
      )}

      {flatSkills.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Skills</h2>
          <ul className={skillList}>
            {flatSkills.map((skill) => (
              <li key={skill.category}>
                <strong>{skill.category}:</strong> {skill.items.join(', ')}
              </li>
            ))}
          </ul>
        </section>
      )}

      {flatAdditionalSkills.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Additional Skills</h2>
          <ul className={skillList}>
            {flatAdditionalSkills.map((skill) => (
              <li key={skill.category}>
                <strong>{skill.category}:</strong> {skill.items.join(', ')}
              </li>
            ))}
          </ul>
        </section>
      )}

      {cv.experience.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Experience</h2>
          {cv.experience.map((job) => (
            <CvEntry
              key={`${job.company}-${job.role}-${job.period}`}
              title={job.role}
              meta={<time>{job.period}</time>}
              org={job.company}
              tech={job.tech.length > 0 ? job.tech.join(', ') : undefined}
            >
              {job.highlights.length > 0 && (
                <ul className={skillList}>
                  {job.highlights.map((highlight) => (
                    <li key={highlight}>{highlight}</li>
                  ))}
                </ul>
              )}
            </CvEntry>
          ))}
        </section>
      )}

      {cv.projects.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Projects</h2>
          {cv.projects.map((project) => (
            <CvEntry
              key={project.name}
              title={project.name}
              meta={
                project.url && (
                  <a href={project.url} target="_blank" rel="noreferrer" className="text-accent">
                    Link
                  </a>
                )
              }
              org={project.description || undefined}
              tech={project.tech.length > 0 ? project.tech.join(', ') : undefined}
            />
          ))}
        </section>
      )}

      {cv.certifications.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Certifications</h2>
          {cv.certifications.map((cert) => (
            <CvEntry key={cert.name} title={cert.name} meta={<time>{cert.date}</time>} org={cert.issuer} />
          ))}
        </section>
      )}

      {cv.publications.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Publications</h2>
          {cv.publications.map((pub) => (
            <CvEntry key={pub.title} title={pub.title} meta={<time>{pub.year}</time>} org={pub.venue} />
          ))}
        </section>
      )}

      {cv.awards.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Awards</h2>
          {cv.awards.map((award) => (
            <CvEntry
              key={award.name}
              title={award.name}
              meta={<time>{award.date}</time>}
              org={award.issuer}
            />
          ))}
        </section>
      )}

      {cv.volunteering.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Volunteering</h2>
          {cv.volunteering.map((vol) => (
            <CvEntry
              key={`${vol.organization}-${vol.role}`}
              title={vol.role}
              meta={<time>{vol.period}</time>}
              org={vol.organization}
            >
              {vol.description && <div>{vol.description}</div>}
            </CvEntry>
          ))}
        </section>
      )}

      {cv.education.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Education</h2>
          {cv.education.map((edu) => (
            <CvEntry
              key={`${edu.institution}-${edu.degree}`}
              title={edu.degree}
              meta={<time>{edu.year}</time>}
              org={edu.institution}
            />
          ))}
        </section>
      )}

      {cv.languages.length > 0 && (
        <section className={section}>
          <h2 className="text-xl text-text-h">Languages</h2>
          <ul className={skillList}>
            {cv.languages.map((lang) => (
              <li key={lang}>{lang}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  )
}
