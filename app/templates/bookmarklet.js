/* Job Search Buddy bookmarklet: reads the job on the current page and opens
   the board's Add job page with it filled in. Served as a javascript: link by
   GET /bookmarklet. */
(function () {
  var APP = "{{ origin }}";
  var host = location.hostname;

  function text(el) {
    if (!el) return "";
    var t = (el.innerText || "").trim();
    var c = (el.textContent || "").trim();
    return t.length >= c.length * 0.6 ? t : c;
  }
  function first(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var el = document.querySelector(selectors[i]);
      var t = text(el);
      if (t) return t;
    }
    return "";
  }
  function decode(s) {
    return s.replace(/&nbsp;|&#xa0;|&#160;/gi, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, "\"").replace(/&#39;|&apos;/g, "'")
      .replace(/&#x([0-9a-f]+);/gi, function (m, h) { return String.fromCharCode(parseInt(h, 16)); })
      .replace(/&#(\d+);/g, function (m, d) { return String.fromCharCode(+d); })
      .replace(/&amp;/g, "&");
  }
  function htmlToText(h) {
    /* Decode first: some sites put entity-encoded HTML ("&lt;ul&gt;") in their job data. */
    return decode(decode(String(h || ""))
      .replace(/<br\s*\/?>|<\/(p|li|div|h[1-6]|ul|ol)>/gi, "\n")
      .replace(/<li[^>]*>/gi, "- ")
      .replace(/<[^>]+>/g, ""))
      .split("\n").map(function (l) { return l.replace(/[ \t]+/g, " ").trim(); })
      .join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }
  function jobPostingData() {
    var scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (var i = 0; i < scripts.length; i++) {
      try {
        var nodes = [].concat(JSON.parse(scripts[i].textContent));
        for (var j = 0; j < nodes.length; j++) {
          var all = [nodes[j]].concat((nodes[j] && nodes[j]["@graph"]) || []);
          for (var k = 0; k < all.length; k++) {
            if (all[k] && [].concat(all[k]["@type"]).indexOf("JobPosting") >= 0) return all[k];
          }
        }
      } catch (e) { /* ignore malformed blocks */ }
    }
    return null;
  }
  function words(s) { return (s.match(/\S+/g) || []).length; }
  var SKIP = /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|SVG|BUTTON|SELECT|IFRAME)$/;
  var BLOCK = /^(P|DIV|SECTION|ARTICLE|MAIN|UL|OL|LI|DL|DT|DD|H[1-6]|TR|TABLE|BLOCKQUOTE|PRE|BR)$/;
  function blockText(root) {
    /* Text with line breaks from the page structure. Unlike innerText it keeps
       visually hidden text, e.g. salary/location kept for screen readers. */
    var out = [];
    (function walk(node) {
      if (node.nodeType === 3) { out.push(node.data); return; }
      if (node.nodeType !== 1 || SKIP.test(node.tagName)) return;
      var block = BLOCK.test(node.tagName);
      if (block) out.push("\n");
      if (node.tagName === "LI") out.push("- ");
      for (var c = node.firstChild; c; c = c.nextSibling) walk(c);
      if (block) out.push("\n");
    })(root);
    return out.join("").split("\n").map(function (l) { return l.replace(/\s+/g, " ").trim(); })
      .filter(function (l) { return l && l !== "-"; }).join("\n");
  }
  function mainText() {
    /* Reader-mode style: credit each paragraph's words to its parent (and half
       to its grandparent), take the best block, widen it while that only adds
       a little, e.g. salary and location bullets just above the paragraphs. */
    var blocks = document.querySelectorAll("p, li, dd, h2, h3, h4, td, blockquote");
    var scores = new Map();
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].closest("nav, header, footer, form, aside")) continue;
      var n = words(blocks[i].textContent || "");
      var parent = blocks[i].parentElement;
      if (!n || !parent) continue;
      scores.set(parent, (scores.get(parent) || 0) + n);
      if (parent.parentElement) scores.set(parent.parentElement, (scores.get(parent.parentElement) || 0) + n / 2);
    }
    var best = null, top = 0;
    scores.forEach(function (score, el) { if (score > top) { top = score; best = el; } });
    if (!best || top < 20) return "";
    while (best.parentElement && best.parentElement !== document.body &&
           words(best.parentElement.textContent || "") <= words(best.textContent || "") * 1.5) {
      best = best.parentElement;
    }
    return blockText(best);
  }
  function meta(name) {
    var el = document.querySelector('meta[property="' + name + '"], meta[name="' + name + '"]');
    return el ? (el.getAttribute("content") || "").trim() : "";
  }

  var job = { title: "", company: "", location: "", url: "", description: "" };
  var extra = [];
  var params = new URLSearchParams(location.search);

  if (/(^|\.)linkedin\.com$/.test(host)) {
    job.title = first([
      ".job-details-jobs-unified-top-card__job-title", ".jobs-unified-top-card__job-title",
      ".top-card-layout__title", ".jobs-details h1", "main h1"]);
    job.company = first([
      ".job-details-jobs-unified-top-card__company-name", ".jobs-unified-top-card__company-name",
      ".topcard__org-name-link", ".top-card-layout__second-subline a"]);
    job.location = first([
      ".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
      ".job-details-jobs-unified-top-card__bullet", ".jobs-unified-top-card__bullet",
      ".topcard__flavor--bullet"]);
    job.description = first([
      "#job-details", ".jobs-description__content", ".jobs-description-content__text",
      ".show-more-less-html__markup", ".description__text"]);
    var arrangement = first([".job-details-fit-level-preferences", ".job-details-preferences-and-skills"]);
    if (arrangement) extra.push("Work arrangement: " + arrangement.replace(/\s+/g, " "));
    if (!job.title || !job.company) {
      /* LinkedIn's tab title is "(2) Job title | Company | LinkedIn". */
      var tparts = document.title.replace(/^\(\d+\)\s*/, "").split(" | ");
      if (tparts.length >= 3 && /linkedin/i.test(tparts[tparts.length - 1])) {
        job.title = job.title || tparts.slice(0, -2).join(" | ");
        job.company = job.company || tparts[tparts.length - 2];
      }
    }
    var liId = params.get("currentJobId") || (location.pathname.match(/\/jobs\/view\/(\d+)/) || [])[1];
    if (liId) job.url = "https://www.linkedin.com/jobs/view/" + liId + "/";
  } else if (/(^|\.)seek\.(com|com\.au|co\.nz)$/.test(host)) {
    job.title = first(['[data-automation="job-detail-title"]', "h1"]);
    job.company = first(['[data-automation="advertiser-name"]']);
    job.location = first(['[data-automation="job-detail-location"]']);
    job.description = first(['[data-automation="jobAdDetails"]']);
    var salary = first(['[data-automation="job-detail-salary"]']);
    var workType = first(['[data-automation="job-detail-work-type"]']);
    if (salary) extra.push("Salary: " + salary);
    if (workType) extra.push("Work type: " + workType);
    var seekId = params.get("jobId") || (location.pathname.match(/\/job\/(\d+)/) || [])[1];
    if (seekId) job.url = location.protocol + "//" + host + "/job/" + seekId;
  }

  var ld = jobPostingData();
  if (ld) {
    var org = ld.hiringOrganization || {};
    job.title = job.title || ld.title || "";
    job.company = job.company || (typeof org === "string" ? org : org.name) || "";
    if (!job.location) {
      var places = [].concat(ld.jobLocation || []).map(function (p) {
        var a = (p && p.address) || {};
        if (typeof a === "string") return a;
        return [a.addressLocality, a.addressRegion].filter(Boolean).join(", ");
      }).filter(Boolean);
      job.location = places.join("; ");
    }
    job.description = job.description || htmlToText(ld.description);
  }

  job.title = job.title || first(["h1"]) || meta("og:title") || document.title;
  job.company = job.company || meta("og:site_name");
  if (!job.company && job.title && document.title.indexOf(job.title) >= 0) {
    /* e.g. "ATO Careers - Deputy Commissioner" -> "ATO" */
    job.company = document.title.replace(job.title, " ")
      .replace(/^[\s|\-\u2013\u2014:]+|[\s|\-\u2013\u2014:]+$/g, "")
      .replace(/\s+(careers?|jobs?)$/i, "").trim();
  }
  job.description = job.description || mainText() || meta("og:description");
  job.url = job.url || location.href.split("#")[0];

  var selected = String(window.getSelection ? window.getSelection() : "").trim();
  if (selected.length > 200) job.description = selected;
  if (extra.length) job.description = extra.join("\n") + "\n\n" + job.description;

  var target = APP + "/jobs/new#" + encodeURIComponent(JSON.stringify(job));
  var win = window.open(target, "_blank");
  if (!win) alert("Job Search Buddy: allow pop-ups for this site, then click the bookmark again.");
})();
