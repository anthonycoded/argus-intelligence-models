import json,random,hashlib,collections,pathlib
out=pathlib.Path('/mnt/data/aic1_synthetic_v2')
# Fictional scenarios, not claims about actual events. Each item is headline, action, follow-up, subtype, difficulty.
defense=[
('Coastal command relocates patrol squadron','A fictional naval command transferred two patrol vessels from its northern base to a southern harbor after a readiness review.','Commanders said the new stationing would shorten response times for maritime surveillance missions.','deployment','standard'),
('Air force begins cold-weather training','Pilots and ground crews conducted a week of simulated runway-recovery drills at a remote military airfield.','The training included aircraft dispersal and emergency refueling under freezing conditions.','exercise','standard'),
('Army orders new counter-drone sensors','A defense procurement office signed a contract to acquire radar units for detecting small unmanned aircraft near bases.','Delivery will occur in phases after acceptance testing and operator training.','procurement','standard'),
('Frigate tests upgraded electronic-warfare suite','Engineers aboard a fictional navy frigate evaluated a revised signal-detection system during controlled sea trials.','The trial measured detection performance against simulated emissions without using live weapons.','technology','standard'),
('Defense ministers sign logistics pact','Two fictional states agreed to share military maintenance facilities and coordinate spare-parts supply during joint deployments.','The agreement establishes planning meetings and procedures for visiting units.','diplomacy','standard'),
('Military headquarters revises reserve mobilization policy','A defense ministry introduced new activation rules for reserve battalions following an internal readiness audit.','The change alters reporting deadlines and command responsibilities during emergencies.','policy','standard'),
('Reconnaissance aircraft expand border patrols','A military air wing added scheduled surveillance flights along a disputed frontier to monitor vehicle movements.','The flights are being coordinated with ground reconnaissance teams.','intelligence','standard'),
('Artillery brigade conducts live-fire certification','Soldiers completed an organized gunnery exercise that tested targeting procedures and ammunition safety controls.','The brigade must pass the certification before deploying to a training rotation.','exercise','standard'),
('Navy receives first autonomous mine-hunting craft','A fictional defense agency accepted delivery of an unmanned surface vessel purchased for naval mine-countermeasure operations.','Crews will undergo military operator qualification before the craft enters service.','procurement','standard'),
('Air-defense unit repositions missile batteries','Military commanders moved surface-to-air missile launchers to protect a newly established forward operating location.','The repositioning was described as temporary and defensive.','deployment','standard'),
('Cyber defense unit investigates base network intrusion','Military incident responders isolated compromised accounts on a command network and began forensic examination.','The defense ministry said operational communications were shifted to an alternate system.','cyber_defense','hard_positive'),
('Military satellites support imagery collection','An armed forces space unit began collecting additional high-resolution images of military staging areas.','Analysts will use the imagery to update operational reconnaissance assessments.','intelligence','standard'),
('Shipyard starts navy propulsion trials','A government defense laboratory ran dockside tests of a prototype propulsion controller intended for attack submarines.','Researchers are measuring noise and reliability before an at-sea demonstration.','technology','standard'),
('Army medical corps changes field evacuation procedures','Military health authorities issued new casualty-evacuation guidance for combat units after recent field exercises.','The directive specifies triage responsibilities and helicopter coordination.','policy','hard_positive'),
('Allied forces establish combined training headquarters','Military officers from three fictional governments launched a shared command cell for annual field exercises.','The cell will develop training objectives and coordinate visiting troops.','diplomacy','standard'),
('Border clash triggers military response','Armed units exchanged fire near a remote frontier post following a reported incursion.','Military officials said reinforcement teams were dispatched and casualties were under assessment.','combat','standard'),
('Naval task group begins maritime interdiction','Warships boarded a suspect vessel during a formally authorized military operation in international waters.','The boarding team reported seizing prohibited military components.','combat','standard'),
('Air force awards aircraft-maintenance contract','A national defense agency contracted a repair firm to overhaul fighter jet engines at a military depot.','Officials said the award supports operational aircraft availability over several years.','procurement','standard'),
('Military academy examines new tactical communications system','Defense researchers tested an encrypted field radio during soldier maneuver experiments.','Operators recorded latency and signal resilience in dense terrain.','technology','standard'),
('Navy and coast guard rehearse port defense','Uniformed naval crews and a civilian maritime service ran a military-led drill against simulated harbor attacks.','The exercise assessed command handoffs and patrol coordination.','exercise','hard_positive'),
('National guard deploys after border alert','A defense ministry mobilized guard units and established temporary checkpoints near strategic crossings.','The units were ordered to support military surveillance and area security.','deployment','standard'),
('Joint defense declaration covers submarine rescue','Two countries signed a military agreement to share specialized diving teams and emergency submarine-rescue equipment.','Defense planners will conduct future interoperability rehearsals.','diplomacy','standard'),
('Military intelligence directorate expands signals team','An armed forces intelligence unit assigned additional analysts to monitor tactical radio activity in a conflict area.','The directorate described the task as part of an ongoing reconnaissance mission.','intelligence','standard'),
('Army trials power systems for field hospitals','Military engineering teams evaluated portable battery equipment designed to power medical facilities near deployed formations.','The tests measured endurance and reliability during simulated outages.','technology','hard_positive'),
('Defense budget adds patrol aircraft funding','Lawmakers approved a military spending measure that finances expansion of the navy maritime-patrol fleet.','The ministry must report progress against its revised force-structure plan.','policy','standard'),
('Combat aviation unit strikes armed positions','Military helicopters launched attacks on identified hostile firing points during an active operation.','An official briefing said ground forces coordinated the strikes.','combat','standard'),
('Military engineering brigade builds river crossing','Combat engineers assembled a temporary bridge as part of a scheduled military maneuver exercise.','Observers tested how quickly armored vehicles could cross under simulated pressure.','exercise','hard_positive'),
('Fighter squadron rotates to allied base','A fictional air force sent six combat aircraft and their crews to an allied installation for a planned deployment.','Host-nation officials confirmed the visiting squadron would remain for several weeks.','deployment','standard'),
('Army changes rules governing unmanned aerial systems','Military leaders issued operational guidance defining how commanders authorize surveillance drones near troop positions.','The rules require additional documentation for data retention and targeting safeguards.','policy','standard'),
('Naval aviation tests carrier landing software','A navy development team evaluated automatic landing assistance during controlled flights from a carrier deck.','Engineers compared performance across different wind conditions.','technology','standard'),
('Defense delegation agrees intelligence sharing','Defense officials signed a memorandum governing exchange of military threat assessments and joint analytic briefings.','The framework establishes handling rules for classified operational information.','diplomacy','standard'),
('Air-defense crews intercept attacking drones','An armed forces air-defense battery engaged unmanned aircraft approaching a protected military installation.','Command officials confirmed the interception occurred during an active security operation.','combat','standard'),
('Military police investigate ammunition depot explosion','An armed forces safety team began an inquiry following an explosion inside a military ammunition storage facility.','The incident disrupted nearby unit operations and triggered a base evacuation.','defense_other','hard_positive'),
('Navy updates personnel deployment rotations','Fleet leadership revised sailor assignment cycles and leave rules to address repeated operational shortages.','The policy affects deployment staffing across several military vessels.','defense_other','hard_positive'),
('Marine corps acquires amphibious vehicles','A military purchasing authority approved an order for specialized armored vehicles used in littoral operations.','Deliveries are subject to acceptance trials and maintenance training.','procurement','standard'),
('Border monitoring unit upgrades tactical sensors','A defense reconnaissance branch installed new ground-sensor nodes to monitor military activity across a frontier.','The unit is evaluating how alerts are incorporated into its intelligence workflow.','intelligence','standard'),
('Reserve troops complete urban mobility drill','A reserve infantry battalion rehearsed street navigation and medical extraction in a purpose-built training town.','The planned exercise used simulated adversaries and no real combat.','exercise','standard'),
('Defense ministers coordinate ammunition production','Military procurement officials from partner states agreed on a joint program for artillery shell production and stockpile resilience.','They announced a framework for shared requirements and subsequent contracts.','diplomacy','standard'),
('Naval unit conducts underwater survey for mines','Military divers and sonar teams investigated possible naval mines near a shipping channel during an active clearance mission.','The armed forces restricted transit until the survey was finished.','combat','hard_positive'),
('Air force opens investigation into training aircraft crash','Military investigators examined the loss of a trainer jet during a routine flight from an air base.','The service suspended similar flights pending a safety review.','defense_other','hard_positive'),
]
nondefense=[
('Transport agencies agree to share aviation data','Civilian regulators from two countries signed a plan to exchange flight-delay statistics and improve airport scheduling.','The arrangement concerns passenger services and includes no military aviation missions.','civilian_transport','hard_negative'),
('Hospital tests emergency drone deliveries','A regional medical center flew small unmanned aircraft carrying blood samples between clinics.','The trial focused on reducing laboratory turnaround times and compliance with civilian aviation rules.','civilian_drones','hard_negative'),
('Museum removes corroded wartime ammunition','Conservation workers coordinated with explosives specialists to secure old shells found beneath a historic exhibition hall.','The items were artifacts from a past conflict, not part of any current armed forces operation.','historical_munitions','hard_negative'),
('Financial regulator changes bond reporting','A central monetary authority published updated disclosure rules for investment firms selling municipal bonds.','The agency expects the change to improve market transparency.','economics','standard'),
('Trade delegation discusses port automation','Commercial shipping executives met customs officials to simplify cargo inspections and introduce automated container tracking.','The discussions centered on trade volumes and delivery costs.','civilian_ports','hard_negative'),
('Power utility expands coastal radar network','Engineers installed weather radar devices to detect approaching storms at offshore wind farms.','The equipment supports turbine safety rather than military surveillance.','civilian_surveillance','hard_negative'),
('University studies missile-shaped meteorite','Researchers described an unusual elongated rock discovered during an astronomy survey.','The analysis was a geological classification, not a weapons program.','keyword_trap','hard_negative'),
('Food safety agency recalls imported produce','Inspectors ordered several wholesalers to withdraw a shipment after detecting contamination.','The announcement concerns consumer health and agricultural trade.','economics','standard'),
('Passenger ferry undergoes security exercise','Port staff practiced evacuation and ticket-screening procedures during a civilian maritime drill.','Local police observed the training, which involved no military units.','civilian_exercise','hard_negative'),
('City publishes cybersecurity incident report','A municipal IT team restored public library accounts after a ransomware attack on its booking website.','The report describes civilian service disruption and password-reset measures.','civilian_cyber','hard_negative'),
('Environmental agency maps coastal erosion','Survey drones collected photographs of beaches threatened by repeated storms.','Scientists will use the images to model shoreline changes.','civilian_drones','hard_negative'),
('Rail operator signs signaling contract','A transit company ordered new traffic-control software to reduce delays across its commuter network.','The contract was financed through a municipal infrastructure program.','transport','standard'),
('Diplomats negotiate academic exchanges','Foreign ministry representatives agreed to expand scholarships and cross-border university collaboration.','The arrangement includes student visas and scientific partnerships, without defense cooperation.','civilian_diplomacy','hard_negative'),
('Manufacturers plan new electric bus plant','A commercial consortium announced investment in a factory producing battery-powered buses.','The project anticipates new jobs and regional supplier contracts.','economics','standard'),
('Tourism board promotes historic naval memorial','City officials unveiled a new walking tour describing sailors who served in a war decades ago.','The project focuses on tourism and cultural preservation rather than current military readiness.','historical_military','hard_negative'),
('Airport introduces biometric boarding','A civilian airline began testing automated identity checks for passengers on international flights.','Regulators said privacy controls and travel-document verification remain under review.','civilian_security','hard_negative'),
('Retail bank suffers phishing campaign','The bank notified customers after criminals sent forged payment messages to account holders.','Its security team blocked suspicious login attempts and recommended multifactor authentication.','civilian_cyber','hard_negative'),
('Farm cooperative expands irrigation systems','Growers completed a reservoir modernization project to improve water availability during dry seasons.','The cooperative expects higher yields and lower energy consumption.','agriculture','standard'),
('Robotics startup demonstrates inspection rover','A private engineering company tested a tracked robot for examining industrial pipelines.','The vehicle is intended for civilian maintenance in hazardous worksites.','dual_use_technology','hard_negative'),
('Border agency upgrades passenger kiosks','Immigration staff installed self-service check-in systems at a busy international terminal.','The equipment reduces queues for travelers and does not involve military border deployments.','civilian_border','hard_negative'),
('Shipping firm reroutes around storm','A container carrier changed its routes to avoid severe weather in a narrow sea passage.','The company described insurance and fuel implications for commercial customers.','shipping','standard'),
('Local council buys aerial firefighting drones','A municipal rescue department purchased aircraft for locating wildfire hotspots and directing volunteer teams.','The procurement is for civilian emergency response, not armed forces operations.','civilian_procurement','hard_negative'),
('Space research institute releases cloud imagery','A public laboratory published satellite observations of seasonal cloud patterns.','The images will support climate forecasting and open academic research.','civilian_satellite','hard_negative'),
('Cultural ministry funds fort restoration','Preservation teams began repairing a nineteenth-century coastal fortress for public visitors.','Restoration plans address historical artifacts and accessibility rather than active military facilities.','historical_military','hard_negative'),
('Government signs electric grid interconnector agreement','Energy ministers agreed to coordinate regulations for a cross-border power cable.','The project aims to stabilize electricity prices and share renewable generation.','energy_diplomacy','hard_negative'),
('Software vendor patches factory control systems','A security bulletin described vulnerabilities in industrial controllers used at civilian water-treatment plants.','Operators were advised to update firmware and audit remote access.','civilian_cyber','hard_negative'),
('Aviation company tests zero-emission aircraft','Engineers completed a battery-powered aircraft demonstration intended for regional passenger routes.','Flight data will guide civilian certification and maintenance standards.','dual_use_technology','hard_negative'),
('Trade ministry discusses sanctions compliance','Commercial banks received guidance on reporting transactions restricted by trade sanctions.','Officials emphasized financial enforcement and did not announce a military operation.','sanctions','hard_negative'),
('City deploys license-plate recognition cameras','Transportation planners introduced cameras to measure congestion around downtown intersections.','Privacy advocates requested limits on retention of commuter travel data.','civilian_surveillance','hard_negative'),
('Port authority clears unexploded historic ordnance','Civilian contractors removed an old shell during expansion work at a commercial dock.','The clearance allowed construction to resume after a temporary safety closure.','historical_munitions','hard_negative'),
('Agriculture agency authorizes drone spraying','Regulators approved limited use of unmanned aircraft for pesticide application over orchards.','Farmers must comply with drift controls and civilian safety requirements.','civilian_drones','hard_negative'),
('Foreign leaders establish disaster relief forum','Representatives from neighboring countries agreed to coordinate humanitarian aid and earthquake warnings.','The meeting concerned civilian disaster management rather than defense policy.','civilian_diplomacy','hard_negative'),
('Shipping consortium reviews fleet cybersecurity','Commercial operators organized a workshop on malicious email and cargo system resilience.','The workshop did not involve military intelligence or defense command networks.','civilian_cyber','hard_negative'),
('City police purchase armored rescue vehicle','A municipal law-enforcement department obtained a protected vehicle for high-risk emergency evacuations.','Funding and command authority remained entirely civilian rather than under the armed forces.','civilian_security','hard_negative'),
('Museum opens exhibition on military satellites','Curators displayed retired spacecraft components and archival photographs from early reconnaissance programs.','The exhibition offers historical education and describes no current military collection operation.','historical_military','hard_negative'),
('Commercial shipbuilder develops autonomous hull','A private firm tested self-navigation software for coastal cargo vessels.','Its research program targets freight efficiency, fuel use, and civilian shipping regulations.','dual_use_technology','hard_negative'),
('Airline launches joint ticketing agreement','Two passenger carriers announced a partnership allowing travelers to book connecting flights across networks.','The arrangement concerns tourism and commercial aviation markets.','transport','standard'),
('Health agency coordinates cross-border disease reporting','Public health ministries created a joint database for monitoring respiratory outbreaks.','Officials will exchange laboratory statistics while maintaining patient privacy safeguards.','civilian_diplomacy','hard_negative'),
('Research team investigates underwater acoustic sensor','Ocean scientists tested hydrophones to track whale migrations along a shipping route.','The instruments collect ecological data and are not associated with naval reconnaissance.','dual_use_technology','hard_negative'),
('Airport security office audits access badges','Civilian terminal managers reviewed employee identification procedures following an unauthorized entry incident.','The review addresses airport operations, not military base security.','civilian_security','hard_negative'),
]
assert len(defense)==len(nondefense)==40
rng=random.Random(20261124)
scenarios=[]
for target,scs in [('defense',defense),('nondefense',nondefense)]:
    for title,detail,follow,subtype,difficulty in scs:
        scenarios.append(dict(fixture_target=target,title=title,detail=detail,follow=follow,scenario_type=subtype,difficulty=difficulty))
rng.shuffle(scenarios)
# Grouped 70/15/15 stratified by class, 28/6/6 unique stories in each class.
splits={}
for target in ['defense','nondefense']:
    ids=[i for i,s in enumerate(scenarios) if s['fixture_target']==target]
    rng.shuffle(ids)
    for j,i in enumerate(ids): splits[i]='train' if j<28 else 'validation' if j<34 else 'test'
records=[];manifest=[]
for i,s in enumerate(scenarios):
    group=f'synv2-story-{i:03d}'
    # 2 different edited representations of the same underlying event: group them in splitting.
    variants=[f"{s['title']}. {s['detail']} {s['follow']}",f"{s['detail']} {s['follow']} The report is headed '{s['title']}'."]
    for j,t in enumerate(variants):
        records.append(dict(fixture_id=f'synv2-{i:03d}-{j}',fixture_target=s['fixture_target'],group_id=group,label_origin='ai_authored_synthetic_fixture_not_human_approval',synthetic=True,text=t))
    manifest.append(dict(group_id=group,split=splits[i],fixture_target=s['fixture_target'],scenario_type=s['scenario_type'],difficulty=s['difficulty']))
rng.shuffle(records)
with (out/'aic1_synthetic_v2.jsonl').open('w',encoding='utf8') as f:
    for r in records:f.write(json.dumps(r,ensure_ascii=False)+'\n')
with (out/'group_splits.jsonl').open('w',encoding='utf8') as f:
    for m in manifest:f.write(json.dumps(m,ensure_ascii=False)+'\n')
summary={
 'dataset_id':'aic1_synthetic_v2','version':'2.0','synthetic':True,
 'total_records':len(records),'unique_scenarios':len(scenarios),'grouped_pairs_per_scenario':2,
 'label_distribution':dict(collections.Counter(r['fixture_target'] for r in records)),
 'split_counts':dict(collections.Counter(splits.values())),
 'split_record_counts':{k:2*v for k,v in collections.Counter(splits.values()).items()},
 'hard_negative_scenarios':sum(s['difficulty']=='hard_negative' for s in scenarios),
 'hard_positive_scenarios':sum(s['difficulty']=='hard_positive' for s in scenarios),
 'generator':'ChatGPT-authored fictional scenarios with deterministic variant formatting',
 'seed':20261124,
 'rights_status':'synthetic_educational_only_not_production_rights_clearance'
}
(out/'manifest.json').write_text(json.dumps(summary,indent=2)+'\n')
# verify genuine variation, split non-overlap, equality
recs=[json.loads(l) for l in (out/'aic1_synthetic_v2.jsonl').read_text(encoding='utf8').splitlines()]
assert len(recs)==160 and len(set(x['text'] for x in recs))==160
assert len(set(x['group_id'] for x in recs))==80
assert set(r['fixture_target'] for r in recs)=={'defense','nondefense'}
assert len(set(m['group_id'] for m in manifest))==80
for spl in ['train','validation','test']:
    groups={m['group_id'] for m in manifest if m['split']==spl}
    assert len([r for r in recs if r['group_id'] in groups])==summary['split_record_counts'][spl]
print(json.dumps(summary,indent=2))
