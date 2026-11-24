# AMR White Paper Source Pack

> Sourced entries for an AMR white paper (32 entries, links re-checked 23 November 2026), each with a verified URL, a short quote, and the claim it supports.

Research-only pack for Content & Comms. Compiled 23 November 2026 (America/Chicago) from the 21 November 2026 scratch fetch under `headers/`, `pages/`, and `quotes/`, then re-verified live. Prefer primary sources. Each entry has title, publisher, date, verified URL, HTTP status, a short verbatim quote, and the claim it supports.

HTTP statuses below were re-checked on 23 November 2026, America/Chicago, unless marked otherwise. A “Nov 21 fetch, URL not recovered” note means the file was saved with HTTP 200 on 21 November 2026, but the original request URL was not stored in the header dump and could not be reconstructed with a live 200 this turn.

---

## 1. MRP history: Orlicky, IBM, APICS, MRP II

### S01. Communications Oriented Production Information and Control System, Volume I (G320-1974)

- **Publisher:** IBM Corporation, Technical Publications Department
- **Date:** Copyright 1972; first edition, second printing, July 1973
- **URL:** https://archive.org/download/bitsavers_ibm370COPIlume1197307_11892753/G320-1974-0_COPICS_Volume_1_197307.pdf (item: https://archive.org/details/bitsavers_ibm370COPIlume1197307_11892753)
- **HTTP status:** 200, `application/pdf`, Content-Length 11892753 (matches the Nov 21 file)
- **Quote:** “COPICS (Communications Oriented Production Information and Control System) is a series of concepts that outline an approach to an integrated computer-based manufacturing control system. The concepts deal with problems common to most companies, from a forecast of customer orders, through development of the master production schedule, to production and shipment of the product.” “The twelve COPICS chapters provide management with a guide for development of a dynamic online manufacturing control system that is terminal and communications oriented and event responsive.”
- **Supports:** IBM published a 1972/73 conceptual blueprint (COPICS) for an integrated, communications-oriented manufacturing control system covering the path from forecast and master schedule through production and shipment. It is presented as a design guide, not a turnkey product. Primary IBM source.

### S02. Material Requirements Planning: The New Way of Life in Production and Inventory Management

- **Publisher:** McGraw-Hill (bibliographic confirmation via AbeBooks listing)
- **Date:** 1975
- **URL:** https://www.abebooks.com/9780070477087/Material-Requirements-Planning-New-Way-0070477086/plp
- **HTTP status:** 200
- **Quote:** The listing identifies the work as “Material Requirements Planning: The New Way of Life in Production and Inventory Management - Orlicky, Joseph,” “Published by McGraw-Hill, 1975,” “ISBN 10: 0070477086 / ISBN 13: 9780070477087.”
- **Supports:** Bibliographic confirmation of Joseph Orlicky’s 1975 McGraw-Hill MRP book (ISBN 0-07-047708-6). This is not a substitute for quoting the book itself; the full text was not retrieved. Scarbrough et al. (S05) cite it as “Orlicky, J. (1975). Materials Requirements Planning. New York: McGraw-Hill.” (title wording differs slightly from the title page on the bookseller listing).

### S03. Manufacturing Resource Planning: MRP II: Unlocking America's Productivity Potential

- **Publisher:** John Wiley & Sons (1984 reprint); Cambridge IfM (S04) cites the 1981 Oliver Wight Ltd. edition
- **Date:** 1981 (Oliver Wight Ltd., as cited by IfM); 1984 Wiley edition on Google Books
- **URL:** https://books.google.com/books/about/Manufacturing_Resource_Planning_MRP_II.html?id=lOy37XbWysgC
- **HTTP status:** 200
- **Quote:** “Manufacturing Resource Planning: MRP II : Unlocking America's Productivity Potential, Oliver W. Wight, John Wiley & Sons, 1984 - Business & Economics - 466 pages,” with chapter heads including “From MRP to MRP II” and “Managing All of the Resources of a Manufacturing Company More Productively.”
- **Supports:** Bibliographic confirmation of Oliver Wight’s MRP II book, the standard primary text for the expansion of MRP into manufacturing resource planning. Full text was not retrieved.

### S04. Manufacturing Resource Planning (MRP II)

- **Publisher:** Institute for Manufacturing, University of Cambridge
- **Date:** Undated explainer; cites Wight 1981
- **URL:** https://www.ifm.eng.cam.ac.uk/research/dstools/mrp-ii/
- **HTTP status:** 200
- **Quote:** “This is a development that seeks to address some of the shortcomings of MRP. It includes all of the elements of MRP.” “MRP II includes the following four major developments from MRP: 1. Feedback … For this reason it is sometimes called 'Closed Loop MRP'. 2. Resource Scheduling … For this reason the initials `MRP' now mean Manufacturing Resources Planning.” Reference: “Wight. O., Manufacturing Resource Planning - Unlocking America's Productivity Potential, Oliver Wight Ltd. Publication Inc, 1981, Essex Jn., VT.”
- **Supports:** A concise, citable university description of how MRP II extends MRP (closed-loop feedback, resource/capacity scheduling, batching rules, and software extensions such as rough-cut capacity planning). Secondary to Wight, but clearer than a bookseller record.

### S05. Diffusion in the Face of Failure: The Evolution of a Management Innovation

- **Publisher:** British Journal of Management (peer-reviewed author manuscript on WRAP); DOI 10.1111/1467-8551.12093
- **Date:** 2015 (WRAP manuscript dated 2015; Wiley version of record)
- **URL:** Landing page https://wrap.warwick.ac.uk/id/eprint/67695/ — PDF https://wrap.warwick.ac.uk/id/eprint/67695/6/WRAP_BJM%20revision%20R4%20final%20revised.pdf
- **HTTP status:** Landing page 200; PDF 200, `application/pdf`, Content-Length 1336991 (matches the Nov 21 file). The bare HTTP URL `http://wrap.warwick.ac.uk/67695` now returns 500; the Wiley DOI resolves to a 403 bot wall.
- **Quote:** “Managers worked independently to develop MRP with support from three consultants (Wight, Plossl or Orlicky). Wight was responsible for naming this approach ‘Materials Requirements Planning (MRP)’. From 1967, this group, who were closely linked to IBM, and to the newly formed professional association for production control – APICS – began to work together developing MRP reports and a certification programme for APICS.” “A watershed in MRP diffusion, however, came with APICS endorsement, which was the outcome of a stormy meeting of the annual conference in 1971 (Orlicky and Burlinghame, 1971) … Plossl stated; ‘In the early 1970s we organized the APICS MRP Crusade…’ (Plossl, 1989: ii).” “Wight referred to this expanded approach as ‘Manufacturing Resource Planning’ and ‘MRP II’ (Wight, 1982; Mabert, 2007).”
- **Supports:** The best academic source in this pack for the APICS role (1971 conference / “MRP Crusade”), the Wight–Plossl–Orlicky group and its IBM link, and Wight’s naming of MRP and MRP II. It is secondary to the 1971 APICS proceedings, which were not retrieved (see caveats).

---

## 2. Gartner’s coining of “ERP” around 1990

### S06. Same paper as S05 (Scarbrough, Robertson and Swan, 2015)

Use S05 as the bibliographic entry. Additional passages and the citation of the Gartner primary:

- **Quote:** “In 1990, the Gartner Group coined the term ‘Enterprise Resource Planning’ (ERP) to denote the new, enterprise-wide scope of the RP innovation, providing adopters with the means to business plan across their entire supply chains (Wylie, 1990).” Bibliography: “Wylie, L. (1990). ’A Vision of Next Generation MRP II’, Scenario S-300-339, Gartner Group, April 12, 1990.” Timeline appendix: “1990 Gartner coin the term ‘enterprise resource planning’ (ERP) expanding the scope of resource planning to the entire supply chain (Wylie, 1990).”
- **Supports:** The standard scholarly attribution: Lee (L.) Wylie, Gartner Group, Scenario S-300-339, 12 April 1990, “A Vision of Next Generation MRP II.” The Gartner note itself was not retrieved and is not known to be freely available (see caveats). Do not cite this pack as if the Gartner primary had been opened.

---

## 3. SAP ECC / Business Suite 7 maintenance: 2027, 2030, and 2033

Precision matters. Official on-premises language is mainstream maintenance through **31 December 2027** and optional extended maintenance through **31 December 2030**. **2033** (and, as of a 13 October 2026 update, a possible run to **31 December 2035** for SAP ERP) is a separate, time-bound **cloud** offering: *SAP ERP, private edition, transition option*, not an extension of on-premises ECC extended maintenance.

### S07. SAP Extends Its Innovation Commitment for SAP S/4HANA, Provides Clarity and Choice on SAP Business Suite 7

- **Publisher:** SAP News Center (SAP Africa)
- **Date:** 5 February 2020
- **URL:** https://news.sap.com/africa/2020/02/sap-extends-its-innovation-commitment-for-sap-s-4hana-provides-clarity-and-choice-on-sap-business-suite-7/
- **HTTP status:** 200
- **Quote:** “WALLDORF — SAP SE (NYSE: SAP) today announced a maintenance commitment for SAP S/4HANA until the end of 2040. At the same time, SAP will provide mainstream maintenance for core applications of SAP Business Suite 7 software* until the end of 2027 followed by optional extended maintenance until the end of 2030.” Footnote: “Core applications of SAP Business Suite 7 software include SAP ERP 6.0, SAP Customer Relationship Management 7.0, SAP Supply Chain Management 7.0, and SAP Supplier Relationship Management 7.0 applications and SAP Business Suite powered by SAP HANA.”
- **Supports:** The original public announcement of the 2040 S/4HANA commitment and of BS7/ECC mainstream-to-2027 plus optional extended maintenance to 2030. SAP ERP 6.0 (ECC) is listed as a BS7 core application.

### S08. Maintenance 2040 (SAP Business Suite 7 / S/4HANA maintenance strategy)

- **Publisher:** SAP Support Portal
- **Date:** Page restates the 4 February 2020 announcement; still the official strategy page as of this check
- **URL:** https://support.sap.com/en/release-upgrade-maintenance/maintenance-information/maintenance-strategy/s4hana-business-suite7.html
- **HTTP status:** 200
- **Quote:** “On February 4, 2020, SAP has announced an innovation commitment for SAP S/4HANA until the end of 2040. … At the same time, SAP will provide mainstream maintenance for SAP Business Suite 7 core applications until end of 2027. This offboarding phase will be followed by optional extended maintenance until end of 2030.” “Customer needing support for their Business Suite 7 core applications in longer conversion phases to SAP S/4HANA can choose the extended maintenance offering. This comes with a premium of two percent points on the maintenance basis … It will be available for three years from beginning of 2028 until end of 2030.” “Customers who do not opt for the extended maintenance, or where extended maintenance has ended, will receive customer specific maintenance…”
- **Supports:** Official terms: 2027 mainstream close, 2028–2030 optional extended maintenance at a +2 percentage-point premium, then customer-specific maintenance. Also points to SAP Notes 2881788, 1648480, and 52505 (login required; not opened here).

### S09. Planning Beyond 2030: What SAP Business Suite 7 and SAP NetWeaver Customers Using Third-Party Databases or Java Need to Know

- **Publisher:** SAP News Center (corporate blog by Philipp Herzig)
- **Date:** 7 October 2026
- **URL:** https://news.sap.com/2026/10/beyond-2030-sap-business-suite-7-sap-netweaver-customers-third-party-databases-java/
- **HTTP status:** 200
- **Quote:** “The dates for SAP Business Suite 7 maintenance have not changed: mainstream maintenance remains available through December 31, 2027, followed by optional extended maintenance through December 31, 2030.” “At the close of the optional extended maintenance period, several support arrangements will expire simultaneously, including SAP’s current reselling and support agreements for third-party databases and Java.” The transition option “is designed to support business continuity from 2031 through 2033 … Systems must be moved to SAP ERP, private edition on SAP HANA before December 31, 2030 … The transition option does not support Java-dependent capabilities.” Continuing on-premise on HANA “does not extend mainstream or optional extended maintenance. The system would still enter customer-specific maintenance…”
- **Supports:** As of October 2026, SAP still treats 31 Dec 2027 / 31 Dec 2030 as unchanged. 2033 is the transition-option window, not extended maintenance. Third-party database and Java resale/support agreements are stated to end with extended maintenance.

### S10. Navigating Your RISE with SAP Journey: Updates for SAP ERP, Private Edition, Transition Option

- **Publisher:** SAP News Center (Stefan Steinle, EVP, Customer Support & Cloud Lifecycle Management)
- **Date:** 4 August 2025; on-page update 13 October 2026
- **URL:** https://news.sap.com/2025/08/rise-with-sap-journey-sap-erp-private-edition-transition-option-updates/
- **HTTP status:** 200
- **Quote:** “SAP recognizes that our largest and most complex SAP ERP customers may not be able to complete this transformation by the end of extended maintenance for their installed SAP Business Suite 7 in 2030.” “SAP has introduced SAP ERP, private edition, transition option – a time-bound subscription offering designed to provide business continuity from 2031 to 2033 while enabling a structured path to SAP Cloud ERP or SAP Cloud ERP Private.” “Update as of October 13, 2026: Subscriptions for transition option for SAP ERP may run until December 31, 2035 (with further prerequisites).” Prerequisites include moving to SAP ERP, private edition on SAP HANA before 31 December 2030, a minimum 2 TB system size, and the max success plan during 2031–2033.
- **Supports:** Public definition of the transition option (2031–2033, with a later ERP-subscription update to 31 Dec 2035) and that it is a cloud subscription for large, complex customers, not on-premises extended maintenance.

---

## 4. VDA 5050 and other AMR / mobile-robot standards

### S11. VDA 5050: Interface for the Communication between Mobile Robots and a Fleet Control, Version 3.0.0

- **Publisher:** VDA (German Association of the Automotive Industry), with VDMA Materials Handling and Intralogistics; technical support from KIT-IFL
- **Date:** March 2026 (GitHub release 18 March 2026, 19:23 UTC)
- **URL:** Specification landing page https://www.vda.de/de/aktuelles/publikationen/publication/vda-5050 (short URL https://www.vda.de/vda-5050 redirects here). Source repo https://github.com/VDA5050/VDA5050 and release https://github.com/VDA5050/VDA5050/releases/tag/3.0.0
- **HTTP status:** All four URLs 200
- **Quote:** Title page: “Interface for the Communication between Mobile Robots and a Fleet Control, VDA 5050, Version 3.0.0, March 2026.” Disclaimer: “The following explanations are intended to provide guidance for implementing an interface that enables communication between mobile robots and a fleet management system. They are intended to be freely accessible to all users and are non-binding.”
- **Supports:** Current official VDA 5050 is 3.0.0 (March 2026), an open, non-binding interface for communication between mobile robots and a fleet control, published by VDA with VDMA and held on GitHub.

### S12. Version 3.0 of VDA 5050 released

- **Publisher:** VDMA e.V., Materials Handling and Intralogistics (press release by Juliane Kluge)
- **Date:** 19 March 2026 (Frankfurt)
- **URL:** Not recovered. PDF was retrieved 21 November 2026 with HTTP 200 (saved as `pages/vdma_press.html`, 186,707 bytes, PDF author Juliane Kluge, created 18 March 2026). The text points readers to https://www.vda.de/vda-5050 and https://github.com/VDA5050/VDA5050 (both 200; see S11).
- **HTTP status:** File 200 on 21 Nov 2026; public press-page URL not reconstructed on 23 Nov 2026
- **Quote:** “Operating different mobile robots with a single control system in a mixed fleet – this is made possible by the VDA 5050 communication interface.” “With version 3.0, the VDMA Materials Handling and Intralogistics Association and the German Association of the Automotive Industry (VDA e.V.) are now expanding the interface so that mobile robots with higher levels of autonomy can also be better integrated.” “The public consultation phase on GitHub, which ran until early February 2026, also yielded a great deal of constructive feedback…”
- **Supports:** VDA 5050 3.0 is a joint VDA/VDMA release aimed at mixed-vendor fleets and higher-autonomy (freely navigating) mobile robots, after a public GitHub consultation.

### S13. Autonomous Mobile Robot Standards Published by MassRobotics

- **Publisher:** MassRobotics
- **Date:** 17 May 2021 (GitHub tag `1.0` published 17 May 2021, 20:13 UTC)
- **URL:** https://www.massrobotics.org/autonomous-mobile-robot-standards-published-by-massrobotics/ and https://github.com/MassRobotics-AMR/AMR_Interop_Standard/releases/tag/1.0
- **HTTP status:** Both 200
- **Quote:** “The standard will allow robots of different types from various vendors to share status information and operational conventions or ‘rules of the road’ so they can better coexist on a warehouse or factory floor.” “The AMR Interoperability Working Group is narrowly focused and will not address safety standards of AMRs and will not duplicate the efforts of ISO under the TC 299 WG (TS 15066, 18646, etc.), the IEEE RAS (such as 1872-2015 or 1873-2015 …) or the RIA (TR 15.606 or ANSI/RIA 15.06).”
- **Supports:** MassRobotics published an AMR interoperability standard (v1.0, May 2021) for multi-vendor coexistence. It is explicitly not a safety standard and is designed not to duplicate ISO, IEEE, or RIA/ANSI safety work.

### S14. What Is the MassRobotics AMR Interoperability Standard?

- **Publisher:** MassRobotics (Kap Choi, BlueBotics)
- **Date:** 19 June 2023
- **URL:** https://www.massrobotics.org/what-is-the-massrobotics-amr-interoperability-standard/
- **HTTP status:** 200
- **Quote:** “The MassRobotics AMR Interoperability Standard allows autonomous mobile robots, or AMRs, from different manufacturers to share their capabilities along with basic information, such as their locations and what they’re doing.” “MassRobotics rolled out Version 1.0 of the interoperability standard in May 2021. Since this version is complete, any automated vehicle manufacturer can implement it. The documentation is available on GitHub.”
- **Supports:** A later explainer confirming v1.0 (May 2021) as the implementable release and that the standard is observational/interop, not a requirement to share proprietary maps.

### S15. ANSI/A3 R15.08, American National Standard for Industrial Mobile Robots (IMRs), IMR Systems and IMR Applications — Safety Requirements — Parts 1, 2, and 3

- **Publisher:** Association for Advancing Automation (A3) Store
- **Date:** Store page “Published April 23, 2026.” Part 1 is a 2026 reaffirmation of the 2020 standard; Part 2 remains the 2023 edition; Part 3 is new in 2026
- **URL:** https://www.automate.org/store/products/ansi-a3-r15-08-american-national-standard-for-industrial-mobile-robots-imrs-imr-systems-and-imr-applications-safety-requirements-parts-1-2-and-3-pdf-download
- **HTTP status:** 200 (product page; the standard text itself is paid)
- **Quote:** “ANSI/A3 R15.08-1-2020 (R2026) - Industrial Mobile Robots (IMRs), is a reaffirmation of Part 1 of R15.08. Reaffirmation means that Part 1 has been re-approved with no technical changes from the original publication in 2020. Part 1 states safety requirements for industrial mobile robots (IMRs); that is, for the individual IMR.” “ANSI/A3 R15.08-2-2023 - IMR Systems and IMR Applications, remains in edition 1, published originally in 2023.” “Part 3 of ANSI/A3 R15.08-2026 - Use of IMR Applications, is an all-new publication.”
- **Supports:** The current U.S. national safety series for industrial mobile robots is ANSI/A3 R15.08, in three parts (robot, system/application integration, and use). This is a catalog description, not a quote from the standard’s normative text.

ISO 3691-4 (driverless industrial trucks / their systems) is the other safety standard named in the brief. Official iso.org catalog pages returned Cloudflare 403 on both 21 and 23 November 2026, so it is in the caveats section rather than as a verified entry.

---

## 5. Agentic AI in manufacturing

### S16. Frontier Technologies in Industrial Operations: The Rise of Artificial Intelligence Agents

- **Publisher:** World Economic Forum, in collaboration with Boston Consulting Group
- **Date:** January 2025
- **URL:** https://reports.weforum.org/docs/WEF_Frontier_Technologies_in_Industrial_Operations_2025.pdf
- **HTTP status:** 200, `application/pdf`, Content-Length 2677049 (matches the Nov 21 file). The weforum.org “publications” HTML page returned 403 to this client.
- **Quote:** White paper title page: “Frontier Technologies in Industrial Operations: The Rise of Artificial Intelligence Agents, WHITE PAPER, JANUARY 2025.” “This document is published by the World Economic Forum as a contribution to a project… © 2025 World Economic Forum.” The paper “focuses on two types of AI agents: virtual AI agents and embodied AI agents.” Box 1: “Virtual AI agents — Software-based AI agents that operate…” “Embodied AI agents — AI agents integrated into physical systems.”
- **Supports:** A dated, citable WEF/BCG industrial-operations paper on AI agents in manufacturing and operations, distinguishing virtual and embodied agents. Disclaimer: findings “do not necessarily represent the views of the World Economic Forum, nor the entirety of its Members.”

### S17. Siemens introduces AI agents for industrial automation

- **Publisher:** Siemens AG press release (Nuremberg/Detroit)
- **Date:** 12 May 2025
- **URL:** https://press.siemens.com/global/en/pressrelease/siemens-introduces-ai-agents-industrial-automation
- **HTTP status:** 200
- **Quote:** “At Automate 2025 in Detroit, Siemens is announcing an expansion of its industrial AI offerings with advanced AI agents designed to work seamlessly across its established Industrial Copilot ecosystem. This new technology represents a fundamental shift from AI assistants that respond to queries towards truly autonomous agents that proactively execute entire processes without human intervention.”
- **Supports:** A named vendor announcement (May 2025) of industrial AI *agents* as distinct from copilots/assistants, aimed at executing processes rather than only answering queries. Treat productivity claims such as “up to 50%” as vendor claims, not independent measurements.

### S18. Siemens brings AI to the physical world with Eigen Engineering Agent

- **Publisher:** Siemens AG press release (Hannover)
- **Date:** 20 April 2026
- **URL:** https://press.siemens.com/global/en/pressrelease/siemens-brings-ai-physical-world-eigen-engineering-agent
- **HTTP status:** 200
- **Quote:** “Today at Hannover Messe, Siemens unveiled the Eigen Engineering Agent – moving industrial AI from assistance to autonomous execution. The Eigen Engineering Agent is among the first commercially available AI systems able to plan and execute industrial automation engineering tasks.”
- **Supports:** A later, productized example (April 2026) of a commercially offered industrial agent for automation engineering, useful as a concrete manufacturing-adjacent case alongside S17.

### S19. Industrial AI in action: How AI agents and digital threads will transform the manufacturing industries

- **Publisher:** Microsoft Cloud Blog (Dayan Rodriguez, Corporate Vice President, Manufacturing and Mobility)
- **Date:** 25 March 2025
- **URL:** https://www.microsoft.com/en-us/microsoft-cloud/blog/manufacturing/2025/03/25/industrial-ai-in-action-how-ai-agents-and-digital-threads-will-transform-the-manufacturing-industries/
- **HTTP status:** 200
- **Quote:** “Manufacturing is set for a major transformation with AI agents. These AI agents are programs that interact with their environment, perceive data, and act on that data, enabling organizations to gain insights, speed up innovation, and transform value chains.” The post announces, among other items, “the public preview of Factory Safety Agent in Copilot Studio.”
- **Supports:** A dated platform-vendor view of manufacturing AI agents (Hannover Messe 2025), with a working definition and named shop-floor agents. It is a Microsoft blog, not an independent evaluation.

### S20. From vision to value: A road map for enterprise transformation in manufacturing with agentic AI

- **Publisher:** Deloitte Insights (Patricia Henderson, Ajay Chavali, Lindsey Berckman, Kate Hardin, John Morehouse)
- **Date:** Published 22 September 2025, 18:30 UTC; page `dateModified` 23 June 2026, 08:30 UTC
- **URL:** https://www.deloitte.com/us/en/insights/industry/manufacturing-industrial-products/agentic-ai-manufacturing-digital-transformation.html
- **HTTP status:** 200
- **Quote:** “According to a survey conducted by the Manufacturing Leadership Council in early 2025, while only 6% of surveyed manufacturers are currently using agentic AI, 24% expect to be using it in just two years—a fourfold increase.” “Agentic AI refers to autonomous generative AI agents that possess ‘agency’—the ability to both act and choose actions to take—which enables them to independently complete complex tasks and achieve human-defined objectives with minimal or no supervision.” Deloitte also cites a Gartner forecast “that 33% of enterprise software will embed agentic AI by 2028—up from less than 1% in 2024—with the ability to make about 15% of routine work decisions autonomously.”
- **Supports:** A usable definition of agentic AI plus a named early-2025 MLC adoption snapshot (6% now / 24% in two years). The Gartner 33%/15% figures are Deloitte’s citation of Gartner, not a primary Gartner document opened here.

---

## 6. Open-source ERP alternatives

### S21. Odoo Community / editions and licenses

- **Publisher:** Odoo S.A.
- **Date:** Editions page current as of check; license text is from the Odoo 20.0 documentation and the `20.0` LICENSE file (LGPLv3, 29 June 2007)
- **URL:** https://www.odoo.com/page/editions ; https://www.odoo.com/documentation/20.0/legal/licenses.html ; https://raw.githubusercontent.com/odoo/odoo/20.0/LICENSE
- **HTTP status:** All 200
- **Quote:** “Our business management software is available in 2 versions: Odoo Community (open-source) and Odoo Enterprise (licensed). Odoo Community is the core upon which Odoo Enterprise is built.” “Odoo 19 Community Edition is licensed under LGPL version 3 (also known as LGPLv3).” “Odoo 19 Enterprise Edition is licensed under the Odoo Enterprise Edition License v1.0.” The `20.0` LICENSE file: “Odoo is published under the GNU LESSER GENERAL PUBLIC LICENSE, Version 3 (LGPLv3).”
- **Supports:** Odoo Community is the open-source (LGPLv3) edition; Enterprise is a separate proprietary license. Manufacturing MRP is marketed at https://www.odoo.com/app/manufacturing (200), but Community vs Enterprise feature split should be taken from the editions comparison, not assumed.

### S22. ERPNext license and current major line

- **Publisher:** Frappe Technologies Pvt. Ltd. and contributors
- **Date:** License policy page current; GitHub release `v16.60.0` published 17 November 2026, 15:01 UTC; Version 16 marketing page also live
- **URL:** https://frappe.io/erpnext/license-trademark ; https://github.com/frappe/erpnext ; https://github.com/frappe/erpnext/releases/tag/v16.60.0 ; https://raw.githubusercontent.com/frappe/erpnext/develop/license.txt ; https://frappe.io/erpnext/version-16
- **HTTP status:** All 200
- **Quote:** “The ERPNext code is licensed as GNU General Public License (v3) and the Documentation is licensed as Creative Commons (CC-BY-SA-3.0) and the copyright is owned by Frappe Technologies Pvt Ltd (Frappe) and Contributors.” “The brand name ERPNext and the logo are trademarks of Frappe Technologies Pvt. Ltd.” Version 16 page: “Almost two years since the last release, ERPNext v16 is finally here… Backed by a global community of 600+ contributors and packed with 50+ new features…”
- **Supports:** ERPNext is GPL-3.0 open-source ERP (trademark remains Frappe’s). The current major line is v16; latest observed patch on 21/23 Nov 2026 was v16.60.0. Frappe also documents MRP at https://docs.frappe.io/erpnext/material-requirements-planning-mrp (200).

### S23. Apache OFBiz

- **Publisher:** Apache Software Foundation, The Apache OFBiz Project
- **Date:** Current stable branch release “Apache OFBiz 24.09.08, Released in November 2026”; Apache License 2.0 dated January 2004
- **URL:** https://ofbiz.apache.org/ ; https://ofbiz.apache.org/download.html ; license text https://www.apache.org/licenses/LICENSE-2.0
- **HTTP status:** All 200
- **Quote:** Project site: “Enjoy the benefits Freedom from vendor lock-in.” “Flexible OFBiz Solutions… ERP with integrated E-Commerce Manufacturing and Warehouse Management CRM, Human Resources, WebPOS and much more.” Downloads: “Apache OFBiz 24.09.08 Released in November 2026.” “Despite our best efforts to maintain up to three active release branches, support for older branches can decrease because our project volunteers may be focused on other issues. We recommend using releases from the most recent branch wherever possible.” LICENSE: “Apache License, Version 2.0, January 2004.”
- **Supports:** OFBiz is an ASF, Apache-2.0 ERP/framework with manufacturing and warehouse modules. Latest observed release 24.09.08 (November 2026). Community support is volunteer-based and concentrated on recent branches.

### S24. iDempiere — Community Powered Enterprise

- **Publisher:** iDempiere community
- **Date:** Project “Founded in 2011”; recommended release “Daily 13 Orion (released 2026-03-06, stable and maintained)”
- **URL:** https://idempiere.org/ ; https://idempiere.org/releases/
- **HTTP status:** Both 200
- **Quote:** “Founded in 2011 iDempiere is a powerful, Tier II, open-source ERP/CRM/SCM system supported by a skilful community.” “iDempiere will be open forever. You will never experience the bitterness of vendor lock-ins.” “State of the art technology right at the heart of iDempiere. Java, ZK, OSGi, Oracle, PostgreSQL, Maven.”
- **Supports:** iDempiere is a living open-source ERP/CRM/SCM project (2011– ), Java/OSGi stack, with a current recommended 2026 “Orion” (v13) line. License is not quoted on the homepage; treat the OSI/open-source claim as project-stated and confirm the exact license in the source repository if the paper needs a SPDX ID.

### S25. Dolibarr ERP CRM

- **Publisher:** Dolibarr association (portal); code on GitHub under GPL-3.0
- **Date:** Association founded 2009 (homepage); latest observed release `24.0.3`, published 11 November 2026, 13:29 UTC
- **URL:** https://www.dolibarr.org/ ; https://github.com/Dolibarr/dolibarr ; https://github.com/Dolibarr/dolibarr/releases/tag/24.0.3 ; https://raw.githubusercontent.com/Dolibarr/dolibarr/develop/COPYING
- **HTTP status:** All 200. The path `https://www.dolibarr.org/license.php` returned 404 (redirected).
- **Quote:** “Used by millions of users worldwide, Dolibarr ERP CRM became a major integrated solution in the Open Source world.” COPYING file is the GNU GPL Version 3, 29 June 2007.
- **Supports:** Dolibarr is an open-source ERP/CRM under GPL-3.0, with a current 24.0.x line (24.0.3 as of 11 Nov 2026). Prefer the GitHub COPYING file over the 404 website license path.

---

## 7. SAP, Infor and QAD support terms, and user-group / survey evidence

### S26. SAP Enterprise Support

- **Publisher:** SAP Support Portal
- **Date:** Current marketing/terms page as of check; the 22% list-price sentence is time-bounded “until 2025”
- **URL:** https://support.sap.com/en/offerings-programs/enterprise-support.html
- **HTTP status:** 200
- **Quote:** “SAP Enterprise Support is included with every cloud subscription. For on-premise customers, a valid maintenance contract is needed.” “The list price for SAP Enterprise Support for new on-premise purchases remains fixed at 22 percent until 2025.” “SAP will not increase fees for existing SAP Enterprise Support contracts during the initial period (1) and first renewal period (2). After the contract is out of the initial price lock SAP may increase the support price by CPI on yearly basis, subject to contract terms (3).”
- **Supports:** Official description of SAP Enterprise Support as the contractual support offering (included in cloud; 22% list for new on-prem, with a stated freeze only “until 2025”). For 2026 commercial terms, use this cautiously and prefer a current price list or contract schedule; the public “until 2025” sentence is already stale.

### S27. Infor Product Lifecycle Policy (Infor General)

- **Publisher:** Infor
- **Date:** PDF created 30 August 2022 (document metadata)
- **URL:** Direct PDF URL not recovered. File retrieved 21 November 2026, HTTP 200, saved as `pages/infor_policy.html` (2,657,501 bytes, 9 pages). Related public support page (200): https://www.infor.com/customer-success/support
- **HTTP status:** PDF 200 on 21 Nov 2026; support page 200 on 23 Nov 2026
- **Quote:** “There are three applicable stages of Maintenance during the product lifecycle of a release: Mainstream Maintenance, Extended Maintenance, and Sustaining Maintenance.” “Mainstream Maintenance is available for every released version of a software product for a period of years following the date of release. … Infor will typically provide notice of such end date one year in advance.” “When available and for an additional fee, Extended Maintenance may be purchased… [it] excludes updates and fixes, except as necessary to resolve Severity 1 incidents.” “Sustaining Maintenance will continue to be made available, for a period of time to be determined by Infor, following expiration of Mainstream Maintenance…”
- **Supports:** Infor’s published general lifecycle model (Mainstream / Extended / Sustaining), with one-year typical notice and no fixed calendar end date in this general policy. Product-specific end dates are stated to live in updated product-specific policies, which were not retrieved.

### S28. QAD Support Solutions Guide, November 2025 Revision

- **Publisher:** QAD (document marked “QAD Confidential”; footer revision date 7 November 2025)
- **Date:** November 2025 (rev. 7 Nov 2025)
- **URL:** Direct PDF URL not recovered. File retrieved 21 November 2026, HTTP 200, saved as `pages/qad_support.html` (528,360 bytes, 11 pages, title “QAD Support Solutions Guide Nov 2025 - Full Version”). A related public page, https://public-supportcenter.qad.com/product-lifecycle, returned 200 on 23 Nov 2026 (body not re-scraped this turn).
- **HTTP status:** PDF 200 on 21 Nov 2026; product-lifecycle page 200 on 23 Nov 2026
- **Quote:** “The Services described apply to ongoing operations and use of QAD solutions on Generally Available (GA) product lifecycle versions & releases along with information about service levels for systems past General Availability.” “This is supplemental to legal documents such as service contracts and program documents.” The guide’s ticket table lists lifecycle statuses including General Availability, Extended Support, Mature, and Retired, and states “Priority 0 & 1 - No variation in service level due to lifecycle status,” with slower Priority 2/3 targets on later statuses. It also describes “Extended Support Services (ESS)” as “additional paid managed service options.”
- **Supports:** QAD publishes a support-guide model with GA and post-GA lifecycle statuses and optional paid Extended Support Services. Exact product end-of-support calendars are in the separate “Product Lifecycle Policy and Schedules,” not fully extracted here. The PDF is marked confidential; quote sparingly and prefer the public product-lifecycle page for anything published.

### S29. UKISUG SAP S/4HANA and RISE Report 2024

- **Publisher:** UK & Ireland SAP User Group (sapusers.org)
- **Date:** 2024 report; PDF metadata created 13 January 2025
- **URL:** Direct PDF URL not recovered. File retrieved 21 November 2026, HTTP 200, saved as `pages/ukisug_2024_pdf.html` (531,545 bytes, 11 pages). The user-group site https://www.sapusers.org/ returned 200.
- **HTTP status:** PDF 200 on 21 Nov 2026; homepage 200 on 23 Nov 2026
- **Quote:** “With the 2027 ECC maintenance deadline moving ever closer, migrating to SAP S/4HANA is a business priority…” “To learn more about how our members are adopting SAP S/4HANA… we surveyed 130 key decision makers at SAP user organisations in the UK and Ireland… studies conducted by USF (185 respondents in France) and VNSG (94 respondents in the Netherlands).” “More than 9 in 10 (94%) UK and Ireland organisations said they are either using (31%) or planning to (63%) to use SAP S/4HANA, up slightly from 92% in 2023.” “Of those organisations that have already deployed SAP S/4HANA in the UK and Ireland, 77% have an on-premise or hosted deployment… only 23% deploying… via S/4HANA Public Cloud… or via S/4HANA Private Cloud… compared to 47% in the Netherlands.”
- **Supports:** A named 2024 user-group survey (n=130 UK&I) showing high planned S/4 adoption but still on-prem-heavy deployments, and that members still talk about a “2027 ECC maintenance deadline” (i.e., mainstream end), which is not the same as the 2030 extended-maintenance close.

### S30. ASUG Research: SAP S/4HANA Adoption Trends, Insights, and Advice

- **Publisher:** Americas’ SAP Users’ Group (Lauren Dixon); report sponsored by BearingPoint
- **Date:** 3 October 2025
- **URL:** https://www.asug.com/insights/sap-s-4hana-adoption-trends-insights-and-advice
- **HTTP status:** 200
- **Quote:** “Sponsored by BearingPoint, 168 ASUG members shared insights into their SAP S/4HANA journeys.” “Even as deadlines for mainstream maintenance of SAP ECC 6.0 approach in 2025 and 2027 *, 56% of ASUG members are currently live or in the process of moving to SAP S/4HANA. That marks an 11% increase over 2024.” “SAP S/4HANA transition can constitute a significant project for many SAP customers, taking an average of one and a half years (based on those surveyed).”
- **Supports:** 2025 ASUG member survey (n=168): 56% live or in process, up 11 points year over year; average migration ~1.5 years. The “2025 and 2027” mainstream wording refers to older enhancement-package cutoffs plus the 2027 core date (see S08); it is not a 2030 extended-maintenance statement.

### S31. How are ERP customers faring with AI readiness? ASUG research reveals that S/4HANA migrations are accelerating…

- **Publisher:** diginomica (Lauren Dixon), reporting later ASUG research
- **Date:** 6 October 2026
- **URL:** https://diginomica.com/how-are-erp-customers-faring-ai-readiness-asug-research-reveals-s4hana-migrations-are-accelerating
- **HTTP status:** 200
- **Quote:** “Research from Americas’ SAP Users’ Group (ASUG) found that the majority of its members (68%) are live or are in the process of moving from SAP ECC to SAP S/4HANA. The report, Navigating SAP S/4HANA - Progress, Opportunities, and the Path to Value, polled 194 members…” “Ahead of the SAP ECC end-of-maintenance deadline next year, SAP customers have been preparing for this move for some time, but 62% are still newcomers with less than three years on S/4HANA.”
- **Supports:** A 2026 ASUG wave (n=194) with 68% live or moving, up from 56% in S30. “End-of-maintenance deadline next year” (i.e., 2027) again tracks mainstream close. This is journalism about the ASUG report, not the report PDF itself.

### S32. Foundry Survey: IT Leaders Express Concern Around SAP Plans for Move to S/4HANA

- **Publisher:** Rimini Street (commissioned Foundry survey), plus CIO coverage of a related Rimini Street survey
- **Date:** Rimini/Foundry page current as retrieved; CIO article at https://www.cio.com/article/4082285/sap-customers-not-sold-on-s-4hana-roi.html (200)
- **URL:** https://www.riministreet.com/resources/research-report/it-leaders-concerned-s4hana-move-foundry-report/
- **HTTP status:** 200
- **Quote:** “Amid recent announcements from SAP and the looming 2027 ECC end of support date, we partnered with Foundry to explore how enterprises view their investments in SAP ERP…” “Key findings include: 67% of ECC/Business Suite customers with perpetual SAP licenses aren’t excited about moving to subscription model; 59% are considering innovating around the edges of existing deployments instead of upgrading; 53% of all surveyed SAP customers are outsourcing some or all of SAP ERP man[agement]…” CIO, on a Rimini Street survey of 455 organizations: “95% saying that making an ROI case for the newer ERP solution is difficult or takes significant effort.”
- **Supports:** Evidence of customer unease around S/4/cloud subscription and ROI. Use with a hard caveat: Rimini Street sells third-party SAP support, so it is not a neutral user-group source. Its “2027 ECC end of support” phrasing also collapses mainstream end with later extended and customer-specific maintenance (contrast S08–S10).

---

## Caveats and unverified items

### Primary sources not opened

- **Gartner Wylie 1990 (S-300-339, 12 April 1990), “A Vision of Next Generation MRP II.”** The pack relies on Scarbrough et al. 2015 (S05/S06) for the citation. The Gartner note was not retrieved and is not known to be free. Jacobs, F. Robert and Weston, F.C. “Ted,” “Enterprise resource planning (ERP)—A brief history,” *Journal of Operations Management* 25 (2007): 357–363, is a second scholarly locus (cited in a CS-history essay we fetched) but was not independently opened.
- **APICS primary texts.** No APICS conference proceeding, “MRP Crusade” document, or APICS/ASCM dictionary was retrieved. The 1971 endorsement / crusade claim rests on S05 quoting Plossl (1989) and Orlicky and Burlingame (1971).
- **Orlicky 1975 and Wight 1981/1984** are confirmed bibliographically (S02, S03) but the books themselves were not read. Do not invent quotations from them.
- **ISO 3691-4** (Industrial trucks — Safety requirements and verification — Part 4: Driverless industrial trucks and their systems), the ISO safety counterpart to ANSI/A3 R15.08, could not be verified on iso.org: `https://www.iso.org/standard/70660.html` returned Cloudflare 403 on 21 and 23 November 2026. A hash-style OBP URL returned a generic 200 for the web app, not a confirmed standard record. Do not treat a 2023 edition as confirmed; the Nov 21 scratch tried a second ISO URL that also failed the challenge. Cite the standard by number only with this limitation, or obtain the official catalog/preview through a human browser session.
- **IEEE 1873-2015** (robot map data representation) was fetched on 21 Nov 2026 (HTTP 200) and is mentioned by MassRobotics (S13) as a standard they would not duplicate. It is not a fleet-interop or IMR safety standard and was left out of the main list to stay lean. The Nov 23 follow of one IEEE URL redirected unpredictably; if used, re-verify `https://standards.ieee.org/ieee/1873/5462/` or the 1873-2015 catalog page in a browser.

### Fetched (HTTP 200 on 21 Nov 2026) but public URL not recovered

These files are in `pages/` and were used above where needed. A stable public URL could not be reconstructed from the header dump on 23 November 2026:

- VDMA press release, “Version 3.0 of VDA 5050 released,” 19 March 2026 (S12).
- Infor Product Lifecycle Policy PDF, 30 August 2022 (S27).
- QAD Support Solutions Guide, November 2025 (S28); also saved but unused as primary: *QAD Cloud Solutions Guide Jul 2026* and *Changes to Software & Cloud Services Terms 20260701*.
- UKISUG *SAP S/4HANA and RISE Report 2024* PDF (S29).
- SAP “Business Suite 7 Extended Maintenance – Commercial Details,” PowerPoint/PDF, SAP SE, created 20 October 2026, and “Transition Option Overview Presentation,” October 2026. Substance is already covered by S08–S10. The Support Portal transition-option HTML, https://support.sap.com/en/release-upgrade-maintenance/maintenance-information/maintenance-strategy/erp-private-transition.html, redirected to a login page (final 200 is a login, not the document).

### Failed or unusable fetches

- **ISO.org catalog pages** and an ANSI blog page: Cloudflare 403 / “Just a moment…”
- **OCLC WorldCat** Orlicky record: 403. AbeBooks (S02) used instead.
- **McKinsey** candidate pages (`mck_advanced`, `mck_agentic_ops`, `mck_coo`): 0-byte header files; no content.
- **DSAG-Investitionsreport 2025** page: HTTP 200 but the saved HTML had no usable article body (cookie/JS wall). Not cited.
- **Dolibarr website license page:** 404. GitHub COPYING used instead (S25).
- **SAP public price list** (`sap_price_list`): 0-byte; not used.
- **geschichte-der-informatik.de, “From MRP to ERP”** (Hans-Joachim Hof): 200, useful as a readable narrative, but it leans on Wikipedia and other secondaries. Not used as a governing source.

### Interpretation cautions

- **2027 vs 2030 vs 2033/2035.** User-group and vendor-survey copy often says “2027 end of support.” Official SAP language is mainstream through 31 Dec 2027, optional extended maintenance through 31 Dec 2030, then customer-specific maintenance on-prem; 2033/2035 is a cloud transition option with eligibility rules (S08–S10, S29–S32).
- **Rimini Street / Foundry / CIO surveys (S32)** are useful for sentiment but are commissioned or amplified by a third-party support vendor. Prefer UKISUG and ASUG (S29–S31) for user-group evidence.
- **SAP Enterprise Support “22 percent until 2025” (S26)** is a dated public sentence; do not present it as a current 2026 price without a newer official schedule.
- **Agentic AI adoption figures** in S20 (MLC 6%/24%; Gartner 33%/15%) are survey or analyst forecasts cited by Deloitte, not primary datasets opened here. Siemens “up to 50%” is a vendor claim (S17/S18).
- **Open-source ERP.** Community/Enterprise splits (Odoo), trademarks (ERPNext), and volunteer branch support (OFBiz) are material. “Open source” on a homepage is not always the same as a stated SPDX license (see iDempiere, S24).
- **QAD Support Solutions Guide** is marked confidential in the PDF footer. Use the quotes above only as research notes unless counsel/comms clears a public citation; the public product-lifecycle URL is the safer outward citation.

---

## Source counts (main list)

| Topic | Sources in this pack | Notes |
| --- | --- | --- |
| 1. MRP history | 5 (S01–S05) | Primary: IBM COPICS. Books bibliographic only. APICS via S05, not APICS itself. |
| 2. Gartner / ERP term | 1 (S06, same paper as S05) | Scholarly citation of Wylie 1990; Gartner primary not opened. |
| 3. SAP 2027 / 2030 / 2033 | 4 (S07–S10) | Official dates are 2027/2030; 2033/2035 is the transition option. |
| 4. AMR / robot standards | 5 (S11–S15) | VDA 5050, MassRobotics, ANSI/A3 R15.08 verified. ISO 3691-4 not verified live. |
| 5. Agentic AI in manufacturing | 5 (S16–S20) | WEF/BCG, Siemens (2), Microsoft, Deloitte. |
| 6. Open-source ERP | 5 (S21–S25) | Odoo CE, ERPNext, OFBiz, iDempiere, Dolibarr. |
| 7. SAP / Infor / QAD support and surveys | 7 (S26–S32) | Official terms plus UKISUG, two ASUG waves, and one third-party survey with caveats. |
| **Total unique documents** | **32 entries (S05=S06 is one paper, so 31 unique)** | Plus the caveats list. |

